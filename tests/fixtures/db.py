"""DB가 필요한 테스트용 fixture.

로컬은 `docker compose up -d`, CI는 Postgres 서비스 컨테이너를 쓴다.

개발용 DB(rag)를 건드리지 않도록 별도의 테스트 DB(rag_test)를 만들어 마이그레이션한다.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from rag_service.config import get_settings

TEST_DATABASE = "rag_test"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _create_test_database() -> None:
    admin_url = get_settings().database_url.set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DATABASE}
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE}"'))
    except OperationalError as error:
        raise RuntimeError(
            "테스트용 Postgres에 연결할 수 없습니다. `docker compose up -d`로 DB를 먼저 켜세요."
        ) from error
    finally:
        admin.dispose()


def migrate(engine: Engine, revision: str = "head", *, downgrade: bool = False) -> None:
    with engine.begin() as connection:
        config = Config(str(ALEMBIC_INI))
        config.attributes["connection"] = connection
        if downgrade:
            command.downgrade(config, revision)
        else:
            command.upgrade(config, revision)


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    _create_test_database()
    engine = create_engine(get_settings().database_url.set(database=TEST_DATABASE))
    migrate(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """테이블을 비운 상태의 세션. 테스트끼리 데이터가 섞이지 않게 한다."""
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE documents, users RESTART IDENTITY CASCADE"))
    with Session(db_engine) as session:
        yield session
