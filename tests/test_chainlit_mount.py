"""Tests for the FastAPI shell mounting the Chainlit runtime."""

import sys

from httpx import ASGITransport, AsyncClient

from capybara.app import create_app


async def test_chainlit_is_mounted() -> None:
    """The ASGI app exposes Chainlit under /chainlit."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/chainlit")
    assert response.status_code in {200, 307, 308}


async def test_chainlit_callbacks_bind_the_canonical_module() -> None:
    """The registered callbacks must live in ``capybara.chainlit_app`` itself.

    Chainlit's load_module executes the mount target as a *new* module instance; if the
    callbacks were registered from that copy, ``configure_chainlit_runtime`` (which sets
    globals on the canonical module) would configure the wrong instance and header auth
    would always reject. The shim target keeps registration on the canonical module —
    this pins that wiring.
    """
    from chainlit.config import config

    import capybara.chainlit_app as canonical

    create_app()  # mounts Chainlit, which loads the target shim

    # The shim must not have produced a second capybara.chainlit_app instance.
    assert sys.modules["capybara.chainlit_app"] is canonical

    registered = config.code.header_auth_callback
    assert registered is not None
    original = registered.__wrapped__  # wrap_user_function uses functools.wraps
    assert original.__globals__ is vars(canonical)
