import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gp_converter.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_sqlite_migrations(engine) -> None:
    """create_all()이 커버하지 못하는 기존 테이블 컬럼 추가.

    Alembic 없이 운영하는 프로젝트라, 기존 files 테이블에 새 컬럼이 생길 때마다
    여기에 (컬럼명, DDL타입) 쌍을 추가한다. 기존 행 데이터는 보존된다.
    """
    if engine.dialect.name != "sqlite":
        return

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(files)"))}
        if "shared_token" not in cols:
            conn.execute(text("ALTER TABLE files ADD COLUMN shared_token VARCHAR"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_files_shared_token ON files (shared_token)"))
        if "shared_expires_at" not in cols:
            conn.execute(text("ALTER TABLE files ADD COLUMN shared_expires_at DATETIME"))
        conn.commit()
