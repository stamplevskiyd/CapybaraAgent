"""Unit tests for the in-process EventBus pub/sub."""

import asyncio
from uuid import uuid4

from capybara.services.event_bus import EventBus


async def test_subscriber_receives_published_event() -> None:
    bus = EventBus()
    uid = uuid4()
    async with bus.subscribe(uid) as queue:
        await bus.publish(uid, {"event": "memory-save", "data": {"n": 1}})
        item = await asyncio.wait_for(queue.get(), timeout=1)
    assert item == {"event": "memory-save", "data": {"n": 1}}


async def test_events_are_isolated_per_user() -> None:
    bus = EventBus()
    a, b = uuid4(), uuid4()
    async with bus.subscribe(a) as qa, bus.subscribe(b) as qb:
        await bus.publish(a, {"event": "x", "data": {}})
        got = await asyncio.wait_for(qa.get(), timeout=1)
        assert got["event"] == "x"
        assert qb.empty()


async def test_publish_with_no_subscribers_is_noop() -> None:
    bus = EventBus()
    uid = uuid4()
    async with bus.subscribe(uid):
        pass  # subscription removed on exit
    await bus.publish(uid, {"event": "x", "data": {}})  # must not raise


async def test_two_subscribers_same_user_both_receive() -> None:
    bus = EventBus()
    uid = uuid4()
    async with bus.subscribe(uid) as q1, bus.subscribe(uid) as q2:
        await bus.publish(uid, {"event": "x", "data": {}})
        assert (await asyncio.wait_for(q1.get(), timeout=1))["event"] == "x"
        assert (await asyncio.wait_for(q2.get(), timeout=1))["event"] == "x"
