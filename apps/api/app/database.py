import os
from collections.abc import Generator
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import settings  # noqa: F401 - load the project .env before creating the engine


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite+pysqlite:///./chess.db")


_url = database_url()
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}
engine = create_engine(_url, future=True, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database() -> None:
    from . import persistence  # noqa: F401

    Base.metadata.create_all(bind=engine)


def assert_database_migrated() -> None:
    api_root = Path(__file__).resolve().parents[1]
    config = Config()
    config.set_main_option("script_location", str(api_root / "alembic"))
    expected = ScriptDirectory.from_config(config).get_current_head()
    with engine.connect() as connection:
        actual = connection.execute(text("SELECT version_num FROM alembic_version")).scalar() if inspect(connection).has_table("alembic_version") else None
    if actual != expected:
        raise RuntimeError("Database migration is required: run alembic upgrade head before starting production")


def reset_database() -> None:
    from . import persistence  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
