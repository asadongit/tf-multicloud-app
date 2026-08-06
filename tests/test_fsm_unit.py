import pytest
from unittest.mock import patch
from app.agent.nodes import find_missing_required, match_task_name, handle_list
from app.agent.state import ConversationState


def test_find_missing_required():
    schema = {
        "type": "object",
        "properties": {
            "instance_type": {"type": "string", "description": "EC2 instance size"},
            "region": {"type": "string", "description": "AWS Region"},
            "tags": {"type": "object", "description": "Optional tags"}
        },
        "required": ["instance_type", "region"]
    }

    # Case 1: All required fields present -> empty missing list
    fields_full = {"instance_type": "t3.micro", "region": "us-east-1", "tags": {"env": "test"}}
    assert find_missing_required(schema, fields_full) == []

    # Case 2: Missing required field -> returns missing key
    fields_partial = {"instance_type": "t3.micro"}
    assert find_missing_required(schema, fields_partial) == ["region"]

    # Case 3: Empty string or None value -> treated as missing
    fields_empty_val = {"instance_type": "", "region": None}
    assert set(find_missing_required(schema, fields_empty_val)) == {"instance_type", "region"}

    # Case 4: Schema with no required array -> returns empty list
    schema_no_req = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert find_missing_required(schema_no_req, {"a": "val"}) == []


def test_match_task_name():
    catalog = [
        {"task_name": "aws-ec2-instance", "title": "AWS EC2 Virtual Machine"},
        {"task_name": "aws-rds-postgres", "title": "AWS RDS PostgreSQL Database"},
        {"task_name": "azure-sql-database", "title": "Azure SQL Database"}
    ]

    # Exact match
    assert match_task_name("I want to deploy aws-ec2-instance please", catalog) == "aws-ec2-instance"

    # Case-insensitive match
    assert match_task_name("Provision AWS-EC2-INSTANCE", catalog) == "aws-ec2-instance"

    # Substring / keyword match
    assert match_task_name("Launch an ec2 instance on aws", catalog) == "aws-ec2-instance"
    assert match_task_name("Deploy azure sql db", catalog) == "azure-sql-database"

    # Non-matching string without pattern
    assert match_task_name("gibberish text 12345", catalog) is None


def test_handle_list_filter_matching():
    state = ConversationState(session_id="test-session")
    mock_catalog = [
        {"task_name": "aws-ec2-instance", "title": "AWS EC2", "category": "compute", "provider": "aws"},
        {"task_name": "aws-rds-postgres", "title": "AWS RDS", "category": "database", "provider": "aws"},
        {"task_name": "azure-vm-instance", "title": "Azure VM", "category": "compute", "provider": "azure"}
    ]

    with patch("app.agent.nodes.get_all_catalog_tasks", return_value=mock_catalog), \
         patch("app.agent.nodes.get_catalog_metadata", return_value=(["compute", "database"], ["aws", "azure"])):

        # 1. Query with category filter
        response_text, trace = handle_list(state, "Show me all compute tasks")
        assert trace[0]["tool"] == "list_tasks"
        assert trace[0]["arguments"].get("category") == "compute"
        assert "aws-ec2-instance" in response_text
        assert "azure-vm-instance" in response_text
        assert "aws-rds-postgres" not in response_text

        # 2. Query with provider filter
        response_text_prov, trace_prov = handle_list(state, "List AWS templates")
        assert trace_prov[0]["tool"] == "list_tasks"
        assert trace_prov[0]["arguments"].get("provider") == "aws"
        assert "aws-ec2-instance" in response_text_prov
        assert "aws-rds-postgres" in response_text_prov

        # 3. Query without filter -> honest presentation of all tasks
        response_text_all, trace_all = handle_list(state, "What tasks can I run?")
        assert "Showing all **3** available tasks" in response_text_all
        assert trace_all[0]["arguments"] == {}
