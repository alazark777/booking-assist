import pytest

from appointment_assistant.agent.tools import ToolDispatcher
from appointment_assistant.domain.models import DomainError, Principal


class Scheduler:
    async def search_slots(self, service, preferred_date, time_preference):
        return []


@pytest.mark.asyncio
async def test_unknown_tool_is_rejected():
    dispatcher = ToolDispatcher(Scheduler())
    with pytest.raises(DomainError, match="not available"):
        await dispatcher.dispatch("run_python", {}, Principal("customer-a"), "session")


@pytest.mark.asyncio
async def test_extra_tool_arguments_are_rejected():
    dispatcher = ToolDispatcher(Scheduler())
    with pytest.raises(DomainError):
        await dispatcher.dispatch("search_slots", {"service": "consultation", "preferred_date": "2026-10-06", "time_preference": "after 17:00", "evil": True}, Principal("customer-a"), "session")
