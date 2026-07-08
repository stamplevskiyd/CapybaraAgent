"""ASGI entrypoint for CapybaraAgent."""

from capybara.app import create_app

app = create_app()
