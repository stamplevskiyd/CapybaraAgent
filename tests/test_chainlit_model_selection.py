"""Tests for per-turn model resolution in the Chainlit runtime."""

from uuid import UUID, uuid4

import pytest

from capybara import chainlit_app


class FakePref:
    def __init__(self, model: str | None) -> None:
        self.model = model


class FakePrefLookup:
    def __init__(self, pref: FakePref | None) -> None:
        self.pref = pref
        self.calls: list[tuple[UUID, UUID]] = []

    async def __call__(self, user_id: UUID, thread_id: UUID) -> FakePref | None:
        self.calls.append((user_id, thread_id))
        return self.pref


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Configure module globals for one test and return a setter for the pref service."""
    user_id = uuid4()
    monkeypatch.setattr(chainlit_app, "_default_model", "default-model")
    monkeypatch.setattr(chainlit_app, "current_user_id", lambda: user_id)

    def set_lookup(lookup: FakePrefLookup | None) -> UUID:
        monkeypatch.setattr(chainlit_app, "_pref_lookup", lookup)
        return user_id

    return set_lookup


async def test_message_metadata_model_wins(configured) -> None:  # type: ignore[no-untyped-def]
    """A model sent with the message itself beats prefs and default."""
    configured(FakePrefLookup(FakePref("pref-model")))
    model = await chainlit_app.selected_model({"model": "meta-model"}, str(uuid4()))
    assert model == "meta-model"


async def test_thread_pref_model_used_when_no_metadata(configured) -> None:  # type: ignore[no-untyped-def]
    service = FakePrefLookup(FakePref("pref-model"))
    user_id = configured(service)
    thread_id = uuid4()

    model = await chainlit_app.selected_model(None, str(thread_id))

    assert model == "pref-model"
    assert service.calls == [(user_id, thread_id)]


async def test_falls_back_to_default_without_pref(configured) -> None:  # type: ignore[no-untyped-def]
    configured(FakePrefLookup(None))
    assert await chainlit_app.selected_model({}, str(uuid4())) == "default-model"


async def test_falls_back_to_default_when_pref_has_no_model(configured) -> None:  # type: ignore[no-untyped-def]
    configured(FakePrefLookup(FakePref(None)))
    assert await chainlit_app.selected_model(None, str(uuid4())) == "default-model"


async def test_falls_back_to_default_for_non_uuid_thread_id(configured) -> None:  # type: ignore[no-untyped-def]
    service = FakePrefLookup(FakePref("pref-model"))
    configured(service)

    assert await chainlit_app.selected_model(None, "not-a-uuid") == "default-model"
    assert service.calls == []


async def test_falls_back_to_default_when_unauthenticated(
    configured, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    configured(FakePrefLookup(FakePref("pref-model")))
    monkeypatch.setattr(chainlit_app, "current_user_id", lambda: None)
    assert await chainlit_app.selected_model(None, str(uuid4())) == "default-model"
