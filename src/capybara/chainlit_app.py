"""Chainlit callbacks for CapybaraAgent chat runtime."""

import chainlit as cl


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize a Chainlit chat session."""
    cl.user_session.set("model", None)  # type: ignore[no-untyped-call]


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Temporary echo handler used until DeepAgents is wired."""
    response = cl.Message(content="")
    await response.stream_token(message.content)
    await response.send()  # type: ignore[no-untyped-call]
