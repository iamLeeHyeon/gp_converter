import asyncio
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.dependencies import get_store
from app.jobs import JobStore, JobStatus

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}/stream")
async def job_stream(job_id: str, store: JobStore = Depends(get_store)):
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
