from sqlalchemy import text
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
