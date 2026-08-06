import json
import pytest
from unittest.mock import patch, AsyncMock

from app.agent.orchestrator import handle_turn
from app.agent.state import load_state, clear_state


@pytest.mark.anyio
async def test_multi_turn_provision_fsm_flow():
    session_id = "test-integration-session-1"
    await clear_state(session_id)

    mock_task_data = {
        "task_name": "aws-ec2-instance",
        "title": "AWS EC2 Virtual Machine",
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_type": {"type": "string", "description": "EC2 instance size"},
                "region": {"type": "string", "description": "AWS Region"}
            },
            "required": ["instance_type", "region"]
        }
    }

    with patch("app.agent.nodes.fetch_task_schema", new_callable=AsyncMock) as mock_fetch_schema, \
         patch("app.agent.nodes.mcp_provision_task", new_callable=AsyncMock) as mock_provision_api, \
         patch("app.agent.nodes.call_llm", new_callable=AsyncMock) as mock_llm_call:

        mock_fetch_schema.return_value = (mock_task_data, mock_task_data["input_schema"])
        mock_provision_api.return_value = json.dumps({
            "status": "QUEUED",
            "deployment_id": "dep-12345",
            "run_id": "run-67890",
            "message": "Deployment queued successfully."
        })

        # Turn 1: User requests provision without field values
        mock_llm_call.side_effect = [
            {"intent": "provision", "confidence": 0.98},  # classify intent
            {}                                            # extract_fields -> empty
        ]

        messages_t1 = [{"role": "user", "content": "I want to provision aws-ec2-instance"}]
        res1 = await handle_turn(messages_t1, session_id=session_id, api_key="gsk_dummy_test_key")

        assert "Please provide the following required parameter(s)" in res1["final_response"]
        assert "instance_type" in res1["final_response"]
        assert "region" in res1["final_response"]

        state_t1 = await load_state(session_id)
        assert state_t1.task_name == "aws-ec2-instance"
        assert set(state_t1.missing_fields) == {"instance_type", "region"}

        # Turn 2: User provides field values
        mock_llm_call.side_effect = [
            {"intent": "provision", "confidence": 0.95},                           # mid-flow check / intent
            {"instance_type": "t3.micro", "region": "us-east-1"}                   # extract_fields
        ]

        messages_t2 = messages_t1 + [
            {"role": "assistant", "content": res1["final_response"]},
            {"role": "user", "content": "instance_type is t3.micro and region is us-east-1"}
        ]
        res2 = await handle_turn(messages_t2, session_id=session_id, api_key="gsk_dummy_test_key")

        assert "Confirmation Required" in res2["final_response"]
        assert "t3.micro" in res2["final_response"]
        assert "us-east-1" in res2["final_response"]

        state_t2 = await load_state(session_id)
        assert state_t2.awaiting_confirmation is True
        assert state_t2.collected_fields == {"instance_type": "t3.micro", "region": "us-east-1"}

        # Turn 3: User confirms deployment
        mock_llm_call.side_effect = [
            {"intent": "confirm", "confidence": 1.0}  # intent confirm
        ]

        messages_t3 = messages_t2 + [
            {"role": "assistant", "content": res2["final_response"]},
            {"role": "user", "content": "yes, confirm deployment"}
        ]
        res3 = await handle_turn(messages_t3, session_id=session_id, api_key="gsk_dummy_test_key")

        assert "Provisioning Queued Successfully!" in res3["final_response"]
        assert "dep-12345" in res3["final_response"]

        mock_provision_api.assert_called_once_with(
            "aws-ec2-instance",
            "aws-ec2-instance-dev",
            {"instance_type": "t3.micro", "region": "us-east-1"}
        )

        state_t3 = await load_state(session_id)
        assert state_t3.intent is None
        assert state_t3.awaiting_confirmation is False


@pytest.mark.anyio
async def test_mid_flow_topic_switching():
    session_id = "test-topic-switch-session"
    await clear_state(session_id)

    mock_task_data = {
        "task_name": "aws-ec2-instance",
        "input_schema": {
            "type": "object",
            "properties": {"instance_type": {"type": "string"}},
            "required": ["instance_type"]
        }
    }

    with patch("app.agent.nodes.fetch_task_schema", new_callable=AsyncMock) as mock_fetch_schema, \
         patch("app.agent.nodes.call_llm", new_callable=AsyncMock) as mock_llm_call:

        mock_fetch_schema.return_value = (mock_task_data, mock_task_data["input_schema"])

        # Step 1: Start provision flow
        mock_llm_call.side_effect = [
            {"intent": "provision", "confidence": 0.98},
            {}
        ]
        res1 = await handle_turn([{"role": "user", "content": "Provision aws-ec2-instance"}], session_id=session_id, api_key="gsk_dummy_test_key")
        assert "instance_type" in res1["final_response"]

        # Step 2: User sends message asking for list of tasks mid-flow
        mock_llm_call.side_effect = [
            {"intent": "list", "confidence": 0.95}  # intent list
        ]
        res2 = await handle_turn([{"role": "user", "content": "actually what tasks are available?"}], session_id=session_id, api_key="gsk_dummy_test_key")

        assert "You're in the middle of provisioning" in res2["final_response"]
        assert "want to abandon that and look at the catalog instead" in res2["final_response"]

        # Step 3: User confirms abandon
        mock_llm_call.side_effect = [
            {"intent": "abandon", "confidence": 1.0}
        ]
        res3 = await handle_turn([{"role": "user", "content": "yes abandon"}], session_id=session_id, api_key="gsk_dummy_test_key")

        state_after = await load_state(session_id)
        assert state_after.task_name is None
