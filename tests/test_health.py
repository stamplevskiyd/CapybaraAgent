from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.api.dependencies import get_session
from capybara.config import Settings
from capybara.main import app


@pytest_asyncio.fixture
async def client(
    engine: AsyncEngine,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession

    from capybara.db.engine import create_sessionmaker

    maker = create_sessionmaker(engine)

    async def _override_session() -> AsyncGenerator[AsyncSession]:
        async with maker() as sess:
            yield sess

    app.dependency_overrides[get_session] = _override_session

    # health() reads request.app.state.settings.ollama_base_url;
    # ASGITransport does not trigger the ASGI lifespan so we supply it directly.
    app.state.settings = settings

    async def _fake_ollama_up(base_url: str) -> bool:  # mirrors real signature
        return True

    monkeypatch.setattr("capybara.api.routers.health.ollama_is_up", _fake_ollama_up)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_health_reports_ok(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "ollama": "up"}
