import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from appointment_assistant.adapters.database import create_engine_and_sessionmaker, create_schema
from appointment_assistant.adapters.repositories import ConversationStore
from appointment_assistant.domain.models import Principal, Slot


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_unique_slot_prevents_concurrent_double_booking():
    database_url = os.getenv("DATABASE_URL")
    if not database_url or not database_url.startswith("postgresql"):
        pytest.skip("Set DATABASE_URL to a PostgreSQL test database")
    engine, factory = create_engine_and_sessionmaker(database_url)
    await create_schema(engine)
    store = ConversationStore(factory)
    suffix = uuid4().hex
    slot = Slot(f"IT-{suffix}", "consultation", "Downtown", datetime.now(timezone.utc), "America/New_York")
    try:
        await store.seed_slots([slot])
        principal_a = Principal(f"it-a-{suffix}")
        principal_b = Principal(f"it-b-{suffix}")
        session_a = await store.get_or_create_session(principal_a, str(uuid4()))
        session_b = await store.get_or_create_session(principal_b, str(uuid4()))
        proposal_a = await store.make_proposal(principal_a, session_a.id, slot.id)
        proposal_b = await store.make_proposal(principal_b, session_b.id, slot.id)
        await store.approve_latest(principal_a, session_a.id, str(uuid4()))
        await store.approve_latest(principal_b, session_b.id, str(uuid4()))

        results = await asyncio.gather(
            store.create_booking(principal_a, session_a.id, proposal_a.id, True),
            store.create_booking(principal_b, session_b.id, proposal_b.id, True),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
    finally:
        await engine.dispose()
