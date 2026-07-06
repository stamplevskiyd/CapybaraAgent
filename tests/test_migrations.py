from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_migrations_create_schema_and_seed(migrated_engine: AsyncEngine) -> None:
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
        assert {"users", "chats", "messages"} <= set(tables)

        count = (
            await conn.execute(text("SELECT count(*) FROM users WHERE username = 'roman'"))
        ).scalar_one()
        assert count == 0

        cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'users'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "password_hash" in set(cols)

        # Verify the seq identity column was added by the migration.
        seq_col = (
            await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'messages' "
                    "AND column_name = 'seq'"
                )
            )
        ).scalar_one_or_none()
        assert seq_col == "seq", "messages.seq column missing — migration did not apply"

        indexes = (
            (
                await conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' "
                        "AND tablename IN ('chats', 'messages')"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "ix_chats_user_id_updated_at" in indexes
        assert "ix_messages_chat_id_seq" in indexes

        assert "facts" in set(tables)

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

        user_cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'users'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "memory_auto_capture" in set(user_cols)

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


async def test_messages_has_tool_calls_column(migrated_engine: AsyncEngine) -> None:
    """The tool_calls JSONB column exists after migrations run."""

    def _columns(sync_conn):  # type: ignore[no-untyped-def]
        return {c["name"] for c in inspect(sync_conn).get_columns("messages")}

    async with migrated_engine.connect() as conn:
        cols = await conn.run_sync(_columns)
    assert "tool_calls" in cols


async def test_messages_has_memory_saves_column(migrated_engine: AsyncEngine) -> None:
    """The memory_saves JSONB column exists after migrations run."""

    def _columns(sync_conn):  # type: ignore[no-untyped-def]
        return {c["name"] for c in inspect(sync_conn).get_columns("messages")}

    async with migrated_engine.connect() as conn:
        cols = await conn.run_sync(_columns)
    assert "memory_saves" in cols
