import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, unique=True, nullable=False)
    provider = Column(String, nullable=False)
    provider_id = Column(String, nullable=False)
    plan = Column(String, nullable=False, default="free")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class File(Base):
    __tablename__ = "files"
    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    gp5_path = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DbJob(Base):
    __tablename__ = "db_jobs"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    file_id = Column(String, ForeignKey("files.id"), nullable=True)
    status = Column(String, nullable=False, default="pending")
    progress_pct = Column(Integer, nullable=False, default=0)
    message = Column(String, nullable=True, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
