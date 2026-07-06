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

    Alembic 없이 운영하는 프로젝트라, 기존 테이블에 새 컬럼이 생길 때마다
    여기에 (컬럼명, DDL타입) 쌍을 추가한다. 기존 행 데이터는 보존된다.
    각 테이블 블록은 해당 테이블이 실제 존재할 때만 실행한다 — 그렇지 않으면
    특정 테이블만 있는 상태로 이 함수를 호출하는 테스트/부분 DB에서 에러가 난다.
    """
    if engine.dialect.name != "sqlite":
        return

    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )}

        if "files" in tables:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(files)"))}
            if "shared_token" not in cols:
                conn.execute(text("ALTER TABLE files ADD COLUMN shared_token VARCHAR"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_files_shared_token ON files (shared_token)"
            ))
            if "shared_expires_at" not in cols:
                conn.execute(text("ALTER TABLE files ADD COLUMN shared_expires_at DATETIME"))

        if "users" in tables:
            user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
            if "stripe_customer_id" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_stripe_customer_id "
                "ON users (stripe_customer_id)"
            ))
            if "password_hash" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR"))
            if "email_verified" not in user_cols:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 1"
                ))
            if "verification_token" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN verification_token VARCHAR"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_verification_token "
                "ON users (verification_token)"
            ))
            if "verification_token_expires_at" not in user_cols:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN verification_token_expires_at DATETIME"
                ))
            if "reset_token" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN reset_token VARCHAR"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_reset_token "
                "ON users (reset_token)"
            ))
            if "reset_token_expires_at" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN reset_token_expires_at DATETIME"))

        conn.commit()
