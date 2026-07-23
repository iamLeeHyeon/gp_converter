import asyncio
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.dependencies import get_store
from app.jobs import JobStore, JobStatus

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}/stream")
async def job_stream(job_id: str, store: JobStore = Depends(get_store)):
    # ponytail: /jobs/{id}, /jobs/{id}/result와 달리 여기는 소유권 체크를
    # 안 한다 — 프론트엔드가 네이티브 브라우저 EventSource로 붙는데 이건
    # 커스텀 Authorization 헤더를 못 보낸다(누가 붙는지 알 방법이 없음).
    # 진행률/상태만 노출되고 실제 결과물(파일 내용)은 안 나가므로 감수함.
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
