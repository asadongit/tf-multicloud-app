import io
import os
import pytest
from app.core.config import settings


def test_create_task_success(client):
    # Prepare dummy terraform script file
    tf_content = b'resource "null_resource" "dummy" {}'
    file_name = "main.tf"
    
    # Create form fields
    payload = {
        "task_name": "test-task",
        "display_name": "Test Task",
        "description": "A test terraform task",
        "input_schema": '{"type": "object", "properties": {"param1": {"type": "string"}}, "required": ["param1"]}',
        "category": "utility",
        "provider": "null",
        "module_version": "1.0.0"
    }
    
    # Send request with authorization header
    headers = {"X-Admin-Token": "admin-token"}
    response = client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": (file_name, io.BytesIO(tf_content), "text/plain")},
        headers=headers
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["display_name"] == "Test Task"
    assert data["provider"] == "null"
    assert data["task_name"] == "test-task"
    assert os.path.exists(data["module_source"])


def test_create_task_unauthorized(client):
    payload = {
        "task_name": "unauthorized-task",
        "display_name": "Test Task",
        "description": "A test terraform task",
        "input_schema": '{"type": "object"}',
    }
    headers = {"X-Admin-Token": "wrong-token"}
    response = client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )
    assert response.status_code == 401


def test_get_and_list_tasks(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create a task first
    payload = {
        "task_name": "fetch-test",
        "display_name": "Fetch Test",
        "description": "To fetch",
        "input_schema": '{"type": "object"}',
    }
    create_response = client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )
    assert create_response.status_code == 201
    task_name = create_response.json()["task_name"]

    # 2. Test List tasks
    list_response = client.get("/api/tasks")
    assert list_response.status_code == 200
    tasks = list_response.json()
    assert len(tasks) == 1
    assert tasks[0]["task_name"] == task_name

    # 3. Test Get single task
    get_response = client.get(f"/api/tasks/{task_name}")
    assert get_response.status_code == 200
    assert get_response.json()["display_name"] == "Fetch Test"

    # 4. Test Get non-existent task
    not_found_response = client.get("/api/tasks/non-existent-name")
    assert not_found_response.status_code == 404


def test_create_task_duplicate_name(client):
    headers = {"X-Admin-Token": "admin-token"}
    payload = {
        "task_name": "duplicate-task",
        "display_name": "Task 1",
        "input_schema": '{"type": "object"}',
    }
    # Create first task
    response1 = client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )
    assert response1.status_code == 201

    # Attempt to create second task with same name
    response2 = client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )
    assert response2.status_code == 400
    assert "already exists" in response2.json()["detail"]


def test_create_task_invalid_name(client):
    headers = {"X-Admin-Token": "admin-token"}
    # Invalid characters like spaces or slashes
    for invalid_name in ["invalid name", "invalid/name", "../invalid", "invalid%name"]:
        payload = {
            "task_name": invalid_name,
            "display_name": "Invalid Task",
            "input_schema": '{"type": "object"}',
        }
        response = client.post(
            "/api/admin/tasks",
            data=payload,
            files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
            headers=headers
        )
        assert response.status_code == 400
        assert "must contain only alphanumeric" in response.json()["detail"]


def test_delete_task(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create a task
    payload = {
        "task_name": "delete-test-task",
        "display_name": "Delete Test Task",
        "input_schema": '{"type": "object"}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )

    # 2. Provision a deployment for this task
    res = client.post(
        "/api/provision/delete-test-task?deployment_name=delete-dep",
        json={},
        headers={"X-User-Id": "owner-1"}
    )
    dep_id = res.json()["deployment_id"]

    # 3. Try to delete task without token -> 401
    del_fail = client.delete("/api/admin/tasks/delete-test-task", headers={"X-Admin-Token": "wrong-token"})
    assert del_fail.status_code == 401

    # 4. Try to delete task with admin token while deployment exists -> 400 Bad Request
    del_blocked = client.delete("/api/admin/tasks/delete-test-task", headers=headers)
    assert del_blocked.status_code == 400
    assert "Cannot delete task" in del_blocked.json()["detail"]

    # 5. Delete the deployment first to allow task deletion
    from unittest.mock import patch, MagicMock
    import time
    from tests.conftest import TestSessionLocal
    from app.models.deployment import Deployment
    mock_destroy = MagicMock(returncode=0, stdout="destroy ok", stderr="")
    run_dir = settings.DEPLOYMENTS_ROOT / dep_id
    run_dir.mkdir(parents=True, exist_ok=True)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_destroy
        del_dep = client.delete(
            f"/api/deployments/{dep_id}",
            headers={"X-User-Id": "owner-1"}
        )
        assert del_dep.status_code == 202

        # Wait for deployment deletion completion (should be removed from DB)
        db = TestSessionLocal()
        try:
            for _ in range(15):
                db.expire_all()
                dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
                if dep is None:
                    break
                time.sleep(0.1)
        finally:
            db.close()

    # 6. Delete task with admin token now that deployment is gone -> 204
    del_success = client.delete("/api/admin/tasks/delete-test-task", headers=headers)
    assert del_success.status_code == 204

    # 7. Verify task is gone from GET list
    list_tasks = client.get("/api/tasks")
    assert not any(t["task_name"] == "delete-test-task" for t in list_tasks.json())


def test_distinct_categories_and_providers_caching(client):
    headers = {"X-Admin-Token": "admin-token"}

    # 1. Query initial distinct endpoints
    res_cat = client.get("/api/categories/distinct")
    assert res_cat.status_code == 200
    assert isinstance(res_cat.json(), list)

    res_prov = client.get("/api/providers/distinct")
    assert res_prov.status_code == 200
    assert isinstance(res_prov.json(), list)

    # 2. Create a task with custom category and provider
    tf_content = b'resource "null_resource" "dummy" {}'
    payload = {
        "task_name": "redis-test-task",
        "display_name": "Redis Test Task",
        "description": "A test terraform task",
        "input_schema": '{"type": "object"}',
        "category": "custom-category",
        "provider": "custom-provider",
        "module_version": "1.0.0"
    }

    create_res = client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(tf_content), "text/plain")},
        headers=headers
    )
    assert create_res.status_code == 201

    # 3. Verify custom category and provider appear in distinct endpoints
    cats = client.get("/api/categories/distinct").json()
    assert "custom-category" in cats

    provs = client.get("/api/providers/distinct").json()
    assert "custom-provider" in provs

    # 4. Delete the task and verify custom category and provider are retired
    del_res = client.delete("/api/admin/tasks/redis-test-task", headers=headers)
    assert del_res.status_code == 204

    cats_after = client.get("/api/categories/distinct").json()
    assert "custom-category" not in cats_after

    provs_after = client.get("/api/providers/distinct").json()
    assert "custom-provider" not in provs_after
