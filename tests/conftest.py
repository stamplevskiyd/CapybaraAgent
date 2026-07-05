import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.postgres import PostgresContainer

from capybara.config import Settings
from capybara.db.base import Base
from capybara.db.engine import create_engine, create_sessionmaker
from capybara.db.models import User
from capybara.security.passwords import hash_password


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
        yield pg


@pytest.fixture(scope="session")
def settings(postgres_container: PostgresContainer) -> Settings:
    # Build Settings from the container's parts (not a URL string): explicit kwargs
    # override any dotenv values, so database_url is derived deterministically.
    return Settings(
        postgres_user=postgres_container.username,
        postgres_password=postgres_container.password,
        postgres_host=postgres_container.get_container_host_ip(),
        postgres_port=int(postgres_container.get_exposed_port(5432)),
        postgres_db=postgres_container.dbname,
        ollama_base_url="http://ollama.test:11434",
        default_model="test-model",
        jwt_secret="test-jwt-secret-key-with-at-least-32-bytes!!",
    )


@pytest_asyncio.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(settings)
    async with eng.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    maker = create_sessionmaker(engine)
    async with maker() as sess:
        yield sess
        await sess.rollback()


@pytest.fixture
def make_user():  # type: ignore[no-untyped-def]
    """Return an async factory that inserts a User with a hashed password."""

    async def _make(
        session: AsyncSession,
        *,
        username: str = "roman",
        display_name: str = "Роман",
        password: str = "password123",
    ) -> User:
        user = User(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
        )
        session.add(user)
        await session.flush()
        return user

    return _make


@pytest_asyncio.fixture
async def migrated_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    # Ensure a clean slate: drop any tables left by other fixtures/tests
    # (e.g. the `engine` fixture uses create_all) before running migrations.
    eng_prep = create_engine(settings)
    async with eng_prep.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
    await eng_prep.dispose()
    # Run synchronous Alembic commands in a thread to avoid "asyncio.run()
    # cannot be called from a running event loop" when env.py calls asyncio.run().
    await asyncio.to_thread(command.upgrade, cfg, "head")
    eng = create_engine(settings)
    yield eng
    await eng.dispose()
    await asyncio.to_thread(command.downgrade, cfg, "base")
