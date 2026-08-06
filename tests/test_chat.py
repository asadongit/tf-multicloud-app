import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.agent.orchestrator import handle_turn
from app.agent.state import clear_state

client = TestClient(app)

def test_chat_page_route():
    """Verify that the GET /chat HTML page serves correctly."""
    response = client.get("/chat")
    assert response.status_code == 200
    assert "Infrastructure AI Assistant" in response.text

def test_chat_missing_api_key():
    """Verify that missing API key returns a 401 Unauthorized status with helpful detail."""
    payload = {
        "messages": [{"role": "user", "content": "List all tasks"}],
        "provider": "groq",
        "api_key": ""
    }
    with patch.dict("os.environ", {"GROQ_API_KEY": ""}, clear=False):
        response = client.post("/api/chat", json=payload)
        assert response.status_code == 401
        assert "API Key for provider" in response.json()["detail"]

@pytest.mark.anyio
async def test_fsm_orchestrator_turn():
    """Test that handle_turn executes deterministic FSM routing and returns standard format."""
    session_id = "test-chat-endpoint-session"
    await clear_state(session_id)

    # 1. Greeting message -> chitchat node (zero tool calls)
    res_chitchat = await handle_turn(
        messages=[{"role": "user", "content": "Hello there"}],
        session_id=session_id,
        provider="groq",
        api_key="gsk_dummy_test_key"
    )
    assert "AI Infrastructure Assistant" in res_chitchat["final_response"]
    assert res_chitchat["execution_trace"] == []

    # 2. List tasks message -> list node (uses Python string matching, zero LLM calls)
    res_list = await handle_turn(
        messages=[{"role": "user", "content": "List all AWS compute tasks"}],
        session_id=session_id,
        provider="groq",
        api_key="gsk_dummy_test_key"
    )
    assert len(res_list["execution_trace"]) == 1
    assert res_list["execution_trace"][0]["tool"] == "list_tasks"
    assert res_list["execution_trace"][0]["arguments"]["provider"] == "aws"

@pytest.mark.anyio
async def test_mcp_tool_schema_alignment():
    """
    CI Safety Test: Asserts that FastMCP server registered tools are accessible.
    """
    from app.mcp_server import mcp

    fastmcp_tools = await mcp.list_tools()
    server_tool_names = {t.name for t in fastmcp_tools}

    expected_tools = {"list_tasks", "get_task_schema", "provision_task", "get_deployment_status", "destroy_deployment", "list_deployments"}
    assert expected_tools == server_tool_names, f"FastMCP tools mismatch: {expected_tools ^ server_tool_names}"
