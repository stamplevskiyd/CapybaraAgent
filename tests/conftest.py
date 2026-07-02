from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.postgres import PostgresContainer

from capybara.config import Settings
from capybara.db.base import Base
from capybara.db.engine import create_engine, create_sessionmaker


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def settings(pg_url: str) -> Settings:
    return Settings(  # type: ignore[call-arg]
        database_url=pg_url,
        ollama_base_url="http://ollama.test:11434",
        default_model="test-model",
    )


@pytest_asyncio.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(settings)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    maker = create_sessionmaker(engine)
    async with maker() as sess:
        yield sess
        await sess.rollback()
