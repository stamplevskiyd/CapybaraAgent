"""Tests for the FastAPI shell mounting the Chainlit runtime."""

from httpx import ASGITransport, AsyncClient

from capybara.app import create_app


async def test_chainlit_is_mounted() -> None:
    """The ASGI app exposes Chainlit under /chainlit."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/chainlit")
    assert response.status_code in {200, 307, 308}
