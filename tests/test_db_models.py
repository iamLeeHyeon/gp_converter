import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import User, File, DbJob


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_tables_exist(engine):
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "users" in tables
    assert "files" in tables
    assert "db_jobs" in tables


def test_user_create(session):
    u = User(email="test@example.com", provider="google", provider_id="g123")
    session.add(u)
    session.commit()
    found = session.query(User).filter_by(email="test@example.com").first()
    assert found is not None
    assert found.plan == "free"
    assert found.id is not None


def test_file_create(session):
    u = User(email="a@b.com", provider="github", provider_id="gh1")
    session.add(u)
    session.commit()
    f = File(user_id=u.id, name="my_song", gp5_path="/tmp/out.gp5")
    session.add(f)
    session.commit()
    found = session.query(File).filter_by(user_id=u.id).first()
    assert found.name == "my_song"


def test_dbjob_progress(session):
    j = DbJob(id="abc123", status="pending", progress_pct=0)
    session.add(j)
    session.commit()
    j.progress_pct = 60
    session.commit()
    found = session.query(DbJob).filter_by(id="abc123").first()
    assert found.progress_pct == 60
