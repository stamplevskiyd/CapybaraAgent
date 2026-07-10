"""Tests for the Chainlit SQLAlchemy data-layer configuration."""

from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

from capybara.chainlit_app import CHAINLIT_DB_SCHEMA, build_data_layer
from capybara.config import Settings


def test_build_data_layer_targets_the_chainlit_schema() -> None:
    """The data layer connects with the app DB URL and scopes to the chainlit schema."""
    settings = Settings(
        postgres_user="u",
        postgres_password="p",
        postgres_host="db",
        postgres_port=5432,
        postgres_db="capy",
        jwt_secret="test-jwt-secret-key-with-at-least-32-bytes!!",
    )

    layer = build_data_layer(settings)

    assert isinstance(layer, SQLAlchemyDataLayer)
    # Chainlit's tables live in their own schema so its `users` never collides with ours.
    assert CHAINLIT_DB_SCHEMA == "chainlit"
    assert layer._conninfo == settings.database_url
