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


def test_migration_creates_unique_index_on_shared_token(tmp_path):
    """마이그레이션 후 shared_token에 unique index가 생성되어야 한다."""
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

    # 첫 번째 row insert 성공
    with engine.connect() as conn:
        conn.execute(sa.text(
            "INSERT INTO files (id, user_id, name, shared_token) "
            "VALUES ('id1', 'user1', 'file1', 'token123')"
        ))
        conn.commit()

    # 두 번째 row (같은 shared_token) insert 실패해야 함
    with engine.connect() as conn:
        try:
            conn.execute(sa.text(
                "INSERT INTO files (id, user_id, name, shared_token) "
                "VALUES ('id2', 'user2', 'file2', 'token123')"
            ))
            conn.commit()
            raise AssertionError("중복 shared_token insert가 실패해야 하는데 성공함")
        except sa.exc.IntegrityError:
            # 예상된 동작: unique constraint 위반
            pass


def test_migration_creates_unique_index_even_if_column_exists(tmp_path):
    """부분 마이그레이션 상태(컬럼 있음, 인덱스 없음)에서도 인덱스를 생성해야 한다."""
    db_path = tmp_path / "partial.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    # 컬럼은 있지만 인덱스는 없는 상태로 테이블 생성 (부분 마이그레이션 시뮬레이션)
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE files ("
            "id VARCHAR PRIMARY KEY, user_id VARCHAR, name VARCHAR, "
            "gp5_path VARCHAR, created_at DATETIME, updated_at DATETIME, "
            "shared_token VARCHAR)"
        ))
        conn.commit()

    run_sqlite_migrations(engine)

    # 첫 번째 row insert 성공
    with engine.connect() as conn:
        conn.execute(sa.text(
            "INSERT INTO files (id, user_id, name, shared_token) "
            "VALUES ('id1', 'user1', 'file1', 'token456')"
        ))
        conn.commit()

    # 두 번째 row (같은 shared_token) insert 실패해야 함 (인덱스가 생성되었다는 증거)
    with engine.connect() as conn:
        try:
            conn.execute(sa.text(
                "INSERT INTO files (id, user_id, name, shared_token) "
                "VALUES ('id2', 'user2', 'file2', 'token456')"
            ))
            conn.commit()
            raise AssertionError("중복 shared_token insert가 실패해야 하는데 성공함 (인덱스 미생성)")
        except sa.exc.IntegrityError:
            # 예상된 동작: unique constraint 위반 (인덱스가 제대로 생성됨)
            pass


def test_migration_adds_stripe_customer_id_column(tmp_path):
    """구버전 users 테이블(신규 컬럼 없음)에 stripe_customer_id를 추가한다."""
    db_path = tmp_path / "old_users.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE users ("
            "id VARCHAR PRIMARY KEY, email VARCHAR, provider VARCHAR, "
            "provider_id VARCHAR, plan VARCHAR, created_at DATETIME)"
        ))
        conn.commit()

    run_sqlite_migrations(engine)

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(users)"))}
    assert "stripe_customer_id" in cols


def test_migration_creates_unique_index_on_stripe_customer_id(tmp_path):
    """마이그레이션 후 stripe_customer_id에 unique index가 생성되어야 한다."""
    db_path = tmp_path / "old_users2.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE users ("
            "id VARCHAR PRIMARY KEY, email VARCHAR, provider VARCHAR, "
            "provider_id VARCHAR, plan VARCHAR, created_at DATETIME)"
        ))
        conn.commit()

    run_sqlite_migrations(engine)

    with engine.connect() as conn:
        conn.execute(sa.text(
            "INSERT INTO users (id, email, provider, provider_id, stripe_customer_id) "
            "VALUES ('u1', 'a@x.com', 'google', 'u1', 'cus_123')"
        ))
        conn.commit()

    with engine.connect() as conn:
        try:
            conn.execute(sa.text(
                "INSERT INTO users (id, email, provider, provider_id, stripe_customer_id) "
                "VALUES ('u2', 'b@x.com', 'google', 'u2', 'cus_123')"
            ))
            conn.commit()
            raise AssertionError("중복 stripe_customer_id insert가 실패해야 하는데 성공함")
        except sa.exc.IntegrityError:
            pass


def test_migration_users_table_missing_is_noop(tmp_path):
    """users 테이블이 없는 DB(예: files만 있는 구버전 테스트 DB)에서도 에러 없이 통과해야 한다.

    이 테스트는 회귀 방지용이다: run_sqlite_migrations가 users 테이블을
    무조건 건드리게 만들면, files만 있는 기존 테스트 DB들(위의 다른 테스트들)이
    전부 'no such table: users'로 깨진다 — 각 테이블 블록은 반드시
    존재 여부를 먼저 확인해야 한다.
    """
    db_path = tmp_path / "files_only.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE files (id VARCHAR PRIMARY KEY, shared_token VARCHAR)"
        ))
        conn.commit()

    run_sqlite_migrations(engine)  # users 테이블 없어도 에러 없이 통과해야 함
