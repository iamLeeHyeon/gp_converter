import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    status: JobStatus
    workdir: str
    message: str = ""
    result_path: str = ""
    progress_pct: int = 0


class JobStore:
    def __init__(self, root: str, ttl_hours: float = 24.0):
        self.root = root
        self.ttl_hours = ttl_hours
        os.makedirs(self.root, exist_ok=True)

    def _meta_path(self, job_id: str) -> str:
        return os.path.join(self.root, job_id, "job.json")

    def _sweep_stale_jobs(self) -> None:
        """TTL이 지난 job 디렉토리(PDF+중간산출물+결과물)를 지운다.

        이 프로젝트엔 스케줄러(Celery beat 등)가 없어서, 새 job을 만들 때마다
        기회적으로 훑어서 지운다 — 로그인 없이도 /convert를 무제한 호출할 수
        있는데 정리 로직이 없으면 디스크가 무한히 누적된다. job.json의
        mtime(마지막 상태 갱신 시각)을 기준으로 판단한다.
        """
        cutoff = time.time() - self.ttl_hours * 3600
        try:
            entries = os.listdir(self.root)
        except OSError:
            return
        for entry in entries:
            job_dir = os.path.join(self.root, entry)
            meta_path = os.path.join(job_dir, "job.json")
            try:
                mtime = os.path.getmtime(meta_path)
            except OSError:
                continue
            if mtime < cutoff:
                shutil.rmtree(job_dir, ignore_errors=True)

    def create(self) -> Job:
        self._sweep_stale_jobs()
        job_id = uuid.uuid4().hex
        workdir = os.path.join(self.root, job_id)
        os.makedirs(workdir, exist_ok=True)
        job = Job(id=job_id, status=JobStatus.QUEUED, workdir=workdir)
        self._write(job)
        return job

    def _write(self, job: Job) -> None:
        data = asdict(job)
        data["status"] = job.status.value
        meta_path = self._meta_path(job.id)
        tmp_path = meta_path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(data, f)
            os.replace(tmp_path, meta_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def get(self, job_id: str) -> Optional[Job]:
        path = self._meta_path(job_id)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            data = json.load(f)
        data["status"] = JobStatus(data["status"])
        return Job(**data)

    def update(self, job_id: str, **fields) -> None:
        """job 필드를 갱신한다.

        read-modify-write이며 전체가 원자적이지 않다(개별 _write만 원자적).
        같은 job_id에 동시에 호출하는 caller가 둘 이상이면 갱신이 덮어써질 수
        있다. 현재 설계는 job마다 백그라운드 워커가 하나뿐이라는 가정에
        의존한다 — 이 가정이 깨지면(예: 같은 job을 여러 워커가 처리) 락이
        필요하다.
        """
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        for k, v in fields.items():
            setattr(job, k, v)
        self._write(job)
