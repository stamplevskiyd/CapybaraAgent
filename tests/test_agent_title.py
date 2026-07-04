"""Tests for LLM chat-title generation and cleaning."""

from capybara.agent.base import _clean_title
from capybara.config import Settings
from support import FakeAgent


def test_clean_title_strips_quotes_and_truncates() -> None:
    assert _clean_title('"Привет мир"', fallback="x") == "Привет мир"
    assert _clean_title("Строка один\nСтрока два", fallback="x") == "Строка один"
    long = "a" * 100
    assert _clean_title(long, fallback="x") == "a" * 60


def test_clean_title_empty_falls_back() -> None:
    assert _clean_title("   ", fallback="Как дела, друг?") == "Как дела, друг?"
    assert _clean_title("''", fallback="Очень длинный вопрос " * 5).__len__() <= 60


async def test_generate_title_returns_cleaned_model_output(settings: Settings) -> None:
    agent = FakeAgent(settings, "Заголовок чата")
    title = await agent.generate_title("test-model", "О чём этот чат?")
    assert title == "Заголовок чата"


async def test_generate_title_falls_back_on_empty_output(settings: Settings) -> None:
    agent = FakeAgent(settings, "")  # model returns empty → fallback to the user message
    title = await agent.generate_title("test-model", "Расскажи про капибар")
    assert title == "Расскажи про капибар"
