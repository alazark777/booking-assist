import pytest

from appointment_assistant.adapters.google_client import FunctionCall, ModelTurn
from appointment_assistant.agent.service import AgentService
from appointment_assistant.domain.models import Principal


class FakeLLM:
    def __init__(self):
        self.calls = 0
        self.contents = []

    async def generate(self, contents, system_prompt, tools, max_output_tokens):
        self.contents.append(contents)
        self.calls += 1
        if self.calls == 1:
            return ModelTurn("", [FunctionCall("search_slots", {"service": "consultation"}, "call-1")])
        return ModelTurn("Here are the available slots.", [])


class Dispatcher:
    async def dispatch(self, name, args, principal, session_id):
        assert name == "search_slots"
        return {"slots": [{"id": "S1"}]}


@pytest.mark.asyncio
async def test_google_continuation_preserves_call_id_and_tool_result():
    llm = FakeLLM()
    agent = AgentService(llm, Dispatcher(), "system", 4, 4, 200)
    result = await agent.run(Principal("customer-a"), "session", [], "find a slot")
    assert result.reply == "Here are the available slots."
    assert result.tool_calls == ["search_slots"]
    response_content = llm.contents[1][-1]
    assert response_content.role == "tool"
    assert response_content.parts[0].function_response.id == "call-1"
