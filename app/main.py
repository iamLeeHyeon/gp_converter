import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Base, engine, get_db
from app.jobs import JobStore, JobStatus
from app.models import User, File as DbFile
from app.routers.auth import router as auth_router
from app.routers.jobs_sse import router as jobs_sse_router
from app.routers.files import router as files_router
from app.worker import process_job

# DB 테이블 자동 생성
Base.metadata.create_all(bind=engine)

app = FastAPI(title="GP Converter")

_FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(jobs_sse_router)
app.include_router(files_router)

_UPLOAD_CHUNK_BYTES = 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_store(settings: Settings = Depends(get_settings)) -> JobStore:
    return JobStore(settings.jobs_dir)


async def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Authorization 헤더가 없으면 None 반환 (비로그인 허용)."""
    from app.auth import decode_token
    import jwt as _jwt
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = decode_token(auth.split(" ", 1)[1])
        if payload.get("type") != "access":
            return None
        return db.query(User).filter(User.id == payload["sub"]).first()
    except (_jwt.ExpiredSignatureError, _jwt.InvalidTokenError):
        return None


@app.post("/convert")
async def convert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: JobStore = Depends(get_store),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
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

    # 로그인 사용자면 File 레코드 예약 생성 (gp5_path는 변환 후 채워짐)
    file_id = None
    if current_user:
        db_file = DbFile(
            user_id=current_user.id,
            name=file.filename or "untitled",
            gp5_path="",  # 변환 완료 후 worker가 업데이트 (Phase 1에서 구현)
        )
        db.add(db_file)
        db.commit()
        db.refresh(db_file)
        file_id = db_file.id

    background_tasks.add_task(
        process_job, store, job.id, pdf_path,
        audiveris_cmd=settings.audiveris_cmd,
        tuxguitar_cmd=settings.tuxguitar_cmd,
        timeout=settings.step_timeout_sec,
    )
    return {"job_id": job.id, "file_id": file_id}


@app.get("/jobs/{job_id}")
async def job_status(job_id: str, store: JobStore = Depends(get_store)):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job 없음")
    return {"status": job.status.value, "message": job.message, "pct": job.progress_pct}


@app.get("/jobs/{job_id}/result")
async def job_result(job_id: str, store: JobStore = Depends(get_store)):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job 없음")
    if job.status != JobStatus.DONE or not job.result_path or not os.path.exists(job.result_path):
        raise HTTPException(status_code=409, detail="아직 결과 없음")
    return FileResponse(job.result_path, media_type="application/octet-stream", filename="score.gp5")


# 프론트엔드 정적 파일 (프로덕션 빌드)
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
