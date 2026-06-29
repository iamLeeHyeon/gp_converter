import json
import os
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
    def __init__(self, root: str):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def _meta_path(self, job_id: str) -> str:
        return os.path.join(self.root, job_id, "job.json")

    def create(self) -> Job:
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
