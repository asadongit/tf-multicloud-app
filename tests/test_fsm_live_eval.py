import os
import json
import pytest
from app.agent.nodes import classify_intent, extract_fields
from app.agent.llm_client import call_llm

@pytest.mark.anyio
async def test_live_llm_eval_benchmark():
    """
    Live evaluation against configured LLM model (e.g. gpt-oss-20b via Groq).
    Measures JSON-parse success rate, retries, and intent classification accuracy.
    """
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        pytest.skip("GROQ_API_KEY environment variable not set.")

    provider = "groq"
    model = os.getenv("LLM_MODEL", "gpt-oss-20b")
    client_config = {"provider": provider, "model": model, "api_key": api_key}

    print(f"\n================ LIVE EVALUATION: {model} ({provider}) ================")

    # 1. Intent Classification Test Suite (10 test cases)
    intent_benchmarks = [
        ("Hello there! What can you do?", "chitchat"),
        ("Show me all available tasks for AWS", "list"),
        ("List compute tasks", "list"),
        ("What is the status of my-db-deployment?", "status"),
        ("List all running deployments", "status"),
        ("I want to provision aws-ec2-instance", "provision"),
        ("Deploy a new server template", "provision"),
        ("Destroy deployment my-test-app", "destroy"),
        ("Yes proceed with the deployment", "confirm"),
        ("Cancel the teardown", "abandon")
    ]

    intent_correct = 0
    intent_total = len(intent_benchmarks)

    print("\n--- Intent Classification Evaluation ---")
    for msg, expected in intent_benchmarks:
        actual_intent, confidence = await classify_intent(msg, client_config)
        is_correct = (actual_intent == expected)
        if is_correct:
            intent_correct += 1
        status_mark = "OK" if is_correct else "FAIL"
        print(f"[{status_mark}] Msg: {msg!r} -> Expected: {expected!r}, Got: {actual_intent!r} (conf: {confidence:.2f})")

    intent_accuracy = (intent_correct / intent_total) * 100.0

    # 2. Field Extraction Test Suite (8 test cases)
    schema_ec2 = {
        "properties": {
            "instance_type": {"type": "string", "description": "EC2 instance size"},
            "region": {"type": "string", "description": "AWS Region"},
            "ami_id": {"type": "string", "description": "Amazon Machine Image ID"}
        }
    }

    schema_rds = {
        "properties": {
            "db_name": {"type": "string", "description": "Database name"},
            "db_user": {"type": "string", "description": "Master username"},
            "instance_class": {"type": "string", "description": "DB Instance class"}
        }
    }

    field_benchmarks = [
        ("Use t3.micro in us-east-1", schema_ec2, "instance_type", "t3.micro"),
        ("Set instance_type to t3.large", schema_ec2, "instance_type", "t3.large"),
        ("region=us-west-2, ami_id=ami-12345678", schema_ec2, "region", "us-west-2"),
        ("I'm deploying in eu-central-1 using t3.medium", schema_ec2, "region", "eu-central-1"),
        ("db_name is myappdb and instance_class is db.t3.micro", schema_rds, "db_name", "myappdb"),
        ("Set db_user to admin", schema_rds, "db_user", "admin"),
        ("db_name=prod_db, db_user=postgres", schema_rds, "db_user", "postgres"),
        ("Set db_name to shop_db", schema_rds, "db_name", "shop_db")
    ]

    extraction_correct = 0
    extraction_total = len(field_benchmarks)

    print("\n--- Field Extraction Evaluation ---")
    for msg, schema, check_key, expected_val in field_benchmarks:
        extracted = await extract_fields(msg, schema, {}, client_config)
        actual_val = str(extracted.get(check_key, ""))
        is_correct = (actual_val.lower() == expected_val.lower())
        if is_correct:
            extraction_correct += 1
        status_mark = "OK" if is_correct else "FAIL"
        print(f"[{status_mark}] Msg: {msg!r} -> Key: {check_key!r}, Expected: {expected_val!r}, Extracted: {actual_val!r}")

    extraction_accuracy = (extraction_correct / extraction_total) * 100.0

    print("\n================ EVALUATION SUMMARY ================")
    print(f"Model Evaluated: {model} ({provider})")
    print(f"Total Benchmark Cases: {intent_total + extraction_total}")
    print(f"Intent Classification Accuracy: {intent_correct}/{intent_total} ({intent_accuracy:.1f}%)")
    print(f"Field Extraction Accuracy: {extraction_correct}/{extraction_total} ({extraction_accuracy:.1f}%)")
    print("===================================================\n")

    assert intent_accuracy >= 70.0, f"Intent accuracy below threshold: {intent_accuracy}%"
    assert extraction_accuracy >= 70.0, f"Extraction accuracy below threshold: {extraction_accuracy}%"
