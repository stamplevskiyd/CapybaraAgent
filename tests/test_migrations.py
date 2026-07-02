from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_migrations_create_schema_and_seed(migrated_engine: AsyncEngine) -> None:
    async with migrated_engine.connect() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        ).scalars().all()
        assert {"users", "chats", "messages"} <= set(tables)

        count = (
            await conn.execute(text("SELECT count(*) FROM users WHERE username = 'roman'"))
        ).scalar_one()
        assert count == 1
