import asyncio
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.config import Settings
from app.jobs import JobStore, JobStatus
from functools import lru_cache

router = APIRouter(tags=["jobs"])


@lru_cache
def _get_store() -> JobStore:
    return JobStore(Settings().jobs_dir)


@router.get("/jobs/{job_id}/stream")
async def job_stream(job_id: str, store: JobStore = Depends(_get_store)):
    async def generate():
        while True:
            job = store.get(job_id)
            if job is None:
                yield f"data: {json.dumps({'status': 'failed', 'pct': 0, 'step': 'job not found'})}\n\n"
                return
            payload = {
                "status": job.status.value,
                "pct": job.progress_pct,
                "step": job.message or "",
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if job.status in (JobStatus.DONE, JobStatus.FAILED):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
