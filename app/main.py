import os
import tempfile
from functools import lru_cache
from pathlib import Path
from fastapi import Depends, FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.jobs import JobStore, JobStatus
from app.worker import process_job
from app.routers.auth import router as auth_router
from app.routers.jobs_sse import router as jobs_sse_router
from app.routers.files import router as files_router

app = FastAPI(title="PDF → Guitar Pro 변환기")
app.include_router(auth_router)
app.include_router(jobs_sse_router)
app.include_router(files_router)

_UPLOAD_CHUNK_BYTES = 1024 * 1024  # 1MB씩 읽어 전체를 메모리에 버퍼링하지 않는다.


@lru_cache
def get_settings() -> Settings:
    """프로세스당 한 번 생성되는 기본 Settings.

    테스트에서는 app.dependency_overrides[get_settings]로 교체한다
    (이 캐시는 override가 적용되면 우회된다).
    """
    return Settings()


def get_store(settings: Settings = Depends(get_settings)) -> JobStore:
    return JobStore(settings.jobs_dir)


@app.post("/convert")
async def convert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: JobStore = Depends(get_store),
):
    fd, tmp_path = tempfile.mkstemp(prefix="upload_", suffix=".pdf")
    checked_magic = False
    try:
        with os.fdopen(fd, "wb") as out:
            total = 0
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                if not checked_magic:
                    if not chunk.startswith(b"%PDF-"):
                        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능")
                    checked_magic = True
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(status_code=400, detail="파일이 너무 큽니다")
                out.write(chunk)
        if not checked_magic:
            raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능")
    except Exception:
        os.remove(tmp_path)
        raise

    job = store.create()
    pdf_path = os.path.join(job.workdir, "input.pdf")
    os.replace(tmp_path, pdf_path)

    background_tasks.add_task(
        process_job, store, job.id, pdf_path,
        audiveris_cmd=settings.audiveris_cmd,
        tuxguitar_cmd=settings.tuxguitar_cmd,
        timeout=settings.step_timeout_sec,
    )
    return {"job_id": job.id}


@app.get("/jobs/{job_id}")
async def job_status(job_id: str, store: JobStore = Depends(get_store)):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job 없음")
    return {"status": job.status.value, "message": job.message}


@app.get("/jobs/{job_id}/result")
async def job_result(job_id: str, store: JobStore = Depends(get_store)):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job 없음")
    if job.status != JobStatus.DONE or not job.result_path or not os.path.exists(job.result_path):
        raise HTTPException(status_code=409, detail="아직 결과 없음")
    return FileResponse(job.result_path, media_type="application/octet-stream", filename="score.gp5")


# 정적 프론트엔드 (Task 9에서 static/index.html 생성)
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
