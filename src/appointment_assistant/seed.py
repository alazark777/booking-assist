from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from appointment_assistant.adapters.database import create_engine_and_sessionmaker
from appointment_assistant.adapters.repositories import ConversationStore
from appointment_assistant.config import get_settings
from appointment_assistant.domain.models import Slot

logger = logging.getLogger(__name__)


def demo_slots(reference: datetime | None = None) -> list[Slot]:
    reference = reference or datetime.now(ZoneInfo("America/New_York"))
    local_date = reference.astimezone(ZoneInfo("America/New_York")).date()
    first = local_date + timedelta(days=1)
    second = local_date + timedelta(days=2)
    return [
        Slot("S1", "consultation", "Downtown", datetime.combine(first, datetime.min.time().replace(hour=17, minute=30), ZoneInfo("America/New_York")), "America/New_York"),
        Slot("S2", "consultation", "Downtown", datetime.combine(second, datetime.min.time().replace(hour=18), ZoneInfo("America/New_York")), "America/New_York"),
        Slot("C1", "cleaning", "Downtown", datetime.combine(first, datetime.min.time().replace(hour=16), ZoneInfo("America/New_York")), "America/New_York"),
    ]


async def main() -> None:
    settings = get_settings()
    engine, factory = create_engine_and_sessionmaker(settings.database_url)
    store = ConversationStore(factory)
    inserted = await store.seed_slots(demo_slots())
    await engine.dispose()
    logger.info("Inserted %d synthetic slots; existing bookings were preserved.", inserted)


if __name__ == "__main__":
    asyncio.run(main())
