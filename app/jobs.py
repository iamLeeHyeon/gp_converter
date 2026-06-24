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
        with open(self._meta_path(job.id), "w") as f:
            json.dump(data, f)

    def get(self, job_id: str) -> Optional[Job]:
        path = self._meta_path(job_id)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            data = json.load(f)
        data["status"] = JobStatus(data["status"])
        return Job(**data)

    def update(self, job_id: str, **fields) -> None:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        for k, v in fields.items():
            setattr(job, k, v)
        self._write(job)
