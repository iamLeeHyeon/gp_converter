import sqlalchemy as sa
from app.database import run_sqlite_migrations


def test_migration_adds_missing_columns(tmp_path):
    """구버전 files 테이블(신규 컬럼 없음)에 컬럼을 추가한다."""
    db_path = tmp_path / "old.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE files ("
            "id VARCHAR PRIMARY KEY, user_id VARCHAR, name VARCHAR, "
            "gp5_path VARCHAR, created_at DATETIME, updated_at DATETIME)"
        ))
        conn.commit()

    run_sqlite_migrations(engine)

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(files)"))}
    assert "shared_token" in cols
    assert "shared_expires_at" in cols


def test_migration_idempotent_on_new_schema(tmp_path):
    """신규 컬럼이 이미 있는 테이블에 다시 실행해도 에러 없이 통과한다."""
    db_path = tmp_path / "new.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE files (id VARCHAR PRIMARY KEY, "
            "shared_token VARCHAR, shared_expires_at DATETIME)"
        ))
        conn.commit()

    run_sqlite_migrations(engine)  # 에러 없이 통과해야 함

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(files)"))}
    assert "shared_token" in cols
    assert "shared_expires_at" in cols


def test_migration_noop_on_non_sqlite(tmp_path):
    """sqlite가 아닌 dialect면 아무 것도 하지 않는다 (postgres 등 향후 대비)."""
    class FakeDialect:
        name = "postgresql"

    class FakeEngine:
        dialect = FakeDialect()
        def connect(self):
            raise AssertionError("postgres에서는 connect가 호출되면 안 됨")

    run_sqlite_migrations(FakeEngine())  # 예외 없이 그냥 리턴
