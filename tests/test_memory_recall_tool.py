from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import Chat
from capybara.services.chat_service import ChatService
from capybara.services.memory_service import MemoryService
from support import ToolCallingFakeAgent


async def test_recall_tool_is_registered_and_reaches_seeded_facts(
    engine: AsyncEngine, settings: Settings, make_user
) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    agent = ToolCallingFakeAgent(settings, "Ответ")

    async with maker() as setup:
        user = await make_user(setup, username="recall", display_name="R")
        chat = Chat(user_id=user.id, title="c", model="test-model")
        setup.add(chat)
        await setup.commit()
        user_id, chat_id = user.id, chat.id

    memory = MemoryService(maker, agent, settings)
    # Seed a fact; agent.embed is constant, so recall returns it.
    await memory.add_fact(user_id, "Любит горные походы", "personal")

    recorded: list[list[str]] = []

    class RecordingMemory(MemoryService):
        async def recall(self, uid, query):  # type: ignore[no-untyped-def]
            facts = await super().recall(uid, query)
            recorded.append([f.content for f in facts])
            return facts

    service = ChatService(maker, agent, RecordingMemory(maker, agent, settings))
    model, history = await service.begin_turn(user_id, chat_id, "Что я люблю?")
    _ = [
        e
        async for e in service.stream_turn(
            chat_id, model, "Что я люблю?", history, user_id=user_id
        )
    ]

    assert recorded, "recall tool was never invoked — tool not registered via the tools list"
    assert any("Любит горные походы" in facts for facts in recorded)
