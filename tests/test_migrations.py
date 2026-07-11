from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_migrations_create_public_schema(migrated_engine: AsyncEngine) -> None:
    async with migrated_engine.connect() as conn:
        tables = (
            (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {"users", "facts", "mcp_servers", "mcp_tools", "chat_prefs"} <= set(tables)

        user_cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'users' AND table_schema = 'public'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "password_hash" in set(user_cols)

        fact_cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'facts'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {"embedding", "category", "source", "user_id"} <= set(fact_cols)

        fact_indexes = (
            (
                await conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' AND tablename = 'facts'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "ix_facts_embedding_hnsw" in fact_indexes
        assert "ix_facts_user_id_created_at" in fact_indexes


async def test_migrations_create_mcp_tables(migrated_engine: AsyncEngine) -> None:
    """The initial schema creates mcp_servers and mcp_tools with their curation fields."""
    async with migrated_engine.connect() as conn:
        cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'mcp_servers'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {"headers", "enabled", "last_connected_at", "last_error"} <= set(cols)


async def test_migrations_create_chat_prefs(migrated_engine: AsyncEngine) -> None:
    """chat_prefs holds per-user thread metadata (favorite, model) keyed by thread_id."""
    async with migrated_engine.connect() as conn:
        cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'chat_prefs'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {"user_id", "thread_id", "is_favorite", "model"} <= set(cols)


async def test_chat_prefs_has_mode_column(migrated_engine: AsyncEngine) -> None:
    """chat_prefs.mode exists after migrations, constrained to fast/smart."""
    async with migrated_engine.connect() as conn:
        cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'chat_prefs'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "mode" in set(cols)
        checks = (
            (
                await conn.execute(
                    text(
                        "SELECT constraint_name FROM information_schema.check_constraints "
                        "WHERE constraint_name = 'ck_chat_prefs_mode'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "ck_chat_prefs_mode" in set(checks)


async def test_chainlit_steps_covers_every_stepdict_key(migrated_engine: AsyncEngine) -> None:
    """chainlit.steps must have a column for every StepDict key the data layer writes.

    SQLAlchemyDataLayer.create_step builds its INSERT from whatever non-None keys the
    step dict carries, so a missing column is a runtime 500 on the first message that
    uses it (autoCollapse bit us live). Pinning against the installed Chainlit's
    StepDict catches this on every dependency upgrade.
    """
    from chainlit.step import StepDict

    # ``feedback`` rides in its own table, never as a steps column.
    expected = set(StepDict.__annotations__) - {"feedback"}
    async with migrated_engine.connect() as conn:
        cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'chainlit' AND table_name = 'steps'"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert expected <= set(cols), f"missing: {expected - set(cols)}"


async def test_migrations_create_chainlit_schema(migrated_engine: AsyncEngine) -> None:
    """Chainlit's data-layer tables land in a dedicated ``chainlit`` schema, not ``public``."""
    async with migrated_engine.connect() as conn:
        chainlit_tables = (
            (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'chainlit'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {"users", "threads", "steps", "elements", "feedbacks"} <= set(chainlit_tables)

        # Chainlit's `users` must not have leaked into public alongside the auth users table.
        public_user_schemas = (
            (
                await conn.execute(
                    text(
                        "SELECT table_schema FROM information_schema.tables "
                        "WHERE table_name = 'users'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(public_user_schemas) == {"public", "chainlit"}
