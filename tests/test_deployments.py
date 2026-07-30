import io
import os
import time
from unittest.mock import patch, MagicMock
import pytest
from app.models.deployment import Deployment, DeploymentStatus
from app.core.config import settings
from tests.conftest import TestSessionLocal


def test_provision_task_success(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create a task with schema requiring "param1"
    payload = {
        "task_name": "provision-test-task",
        "display_name": "Provision Test Task",
        "input_schema": '{"type": "object", "properties": {"param1": {"type": "string"}}, "required": ["param1"]}',
    }
    create_response = client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )
    assert create_response.status_code == 201

    # 2. Provision the task with valid inputs (flat payload)
    provision_payload = {"param1": "hello"}
    provision_response = client.post(
        "/api/provision/provision-test-task?deployment_name=my-deployment",
        json=provision_payload,
        headers={"X-User-Id": "test-owner"}
    )
    
    assert provision_response.status_code == 202
    data = provision_response.json()
    assert "run_id" in data
    assert "deployment_id" in data
    assert data["deployment_name"] == "my-deployment"
    assert data["task_name"] == "provision-test-task"
    assert data["status"] == "PROVISIONING"


def test_provision_task_not_found(client):
    response = client.post(
        "/api/provision/non-existent-task?deployment_name=my-deployment",
        json={}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_provision_task_schema_validation_failure(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create task requiring "param1" as string
    payload = {
        "task_name": "validation-test-task",
        "display_name": "Validation Test Task",
        "input_schema": '{"type": "object", "properties": {"param1": {"type": "string"}}, "required": ["param1"]}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )

    # 2. Provision with missing "param1"
    response1 = client.post(
        "/api/provision/validation-test-task?deployment_name=deploy-1",
        json={}
    )
    assert response1.status_code == 422
    assert "inputs failed schema validation" in response1.json()["detail"]

    # 3. Provision with wrong type for "param1"
    response2 = client.post(
        "/api/provision/validation-test-task?deployment_name=deploy-2",
        json={"param1": 123}
    )
    assert response2.status_code == 422
    assert "inputs failed schema validation" in response2.json()["detail"]


def test_provision_task_duplicate_deployment_name(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create task
    payload = {
        "task_name": "duplicate-deploy-task",
        "display_name": "Duplicate Deploy Task",
        "input_schema": '{"type": "object"}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )

    # 2. Provision first deployment
    response1 = client.post(
        "/api/provision/duplicate-deploy-task?deployment_name=same-name",
        json={},
        headers={"X-User-Id": "owner-1"}
    )
    assert response1.status_code == 202

    # 3. Provision second deployment with same name for same owner -> should fail
    response2 = client.post(
        "/api/provision/duplicate-deploy-task?deployment_name=same-name",
        json={},
        headers={"X-User-Id": "owner-1"}
    )
    assert response2.status_code == 400
    assert "already have a deployment named" in response2.json()["detail"]

    # 4. Provision deployment with same name for DIFFERENT owner -> should succeed
    response3 = client.post(
        "/api/provision/duplicate-deploy-task?deployment_name=same-name",
        json={},
        headers={"X-User-Id": "owner-2"}
    )
    assert response3.status_code == 202


def test_worker_execution_success(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create a task
    payload = {
        "task_name": "worker-test-task",
        "display_name": "Worker Test Task",
        "input_schema": '{"type": "object"}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b"variable 'x' {}"), "text/plain")},
        headers=headers
    )

    # 2. Mock subprocess.run
    mock_init = MagicMock(returncode=0, stdout="init ok", stderr="")
    mock_apply = MagicMock(returncode=0, stdout="apply ok", stderr="")
    mock_output = MagicMock(returncode=0, stdout='{"out1": {"value": "val1"}}', stderr="")
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [mock_init, mock_apply, mock_output]
        
        # Provision task (flat payload)
        response = client.post(
            "/api/provision/worker-test-task?deployment_name=worker-dep",
            json={},
            headers={"X-User-Id": "owner-1"}
        )
        assert response.status_code == 202
        data = response.json()
        dep_id = data["deployment_id"]

        # Wait up to 1.5 seconds for the background asyncio task to complete
        db = TestSessionLocal()
        try:
            for _ in range(15):
                db.expire_all()
                dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
                if dep and dep.status in [DeploymentStatus.ACTIVE, DeploymentStatus.FAILED]:
                    break
                time.sleep(0.1)
                
            dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
            assert dep is not None
            assert dep.status == DeploymentStatus.ACTIVE
            assert dep.outputs == {"out1": "val1"}
            assert "terraform.tfstate" in dep.state_path
            assert mock_run.call_count == 3
        finally:
            db.close()


def test_get_and_list_deployments(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create task
    payload = {
        "task_name": "list-dep-task",
        "display_name": "List Dep Task",
        "input_schema": '{"type": "object"}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )

    # 2. Provision two deployments for owner-1 (flat payload)
    res1 = client.post(
        "/api/provision/list-dep-task?deployment_name=dep-1",
        json={},
        headers={"X-User-Id": "owner-1"}
    )
    dep_id_1 = res1.json()["deployment_id"]

    res2 = client.post(
        "/api/provision/list-dep-task?deployment_name=dep-2",
        json={},
        headers={"X-User-Id": "owner-1"}
    )
    dep_id_2 = res2.json()["deployment_id"]

    # 3. Provision one deployment for owner-2 (flat payload)
    res3 = client.post(
        "/api/provision/list-dep-task?deployment_name=dep-3",
        json={},
        headers={"X-User-Id": "owner-2"}
    )

    # 4. List deployments for owner-1
    list_res_1 = client.get("/api/deployments", headers={"X-User-Id": "owner-1"})
    assert list_res_1.status_code == 200
    deps_1 = list_res_1.json()
    assert len(deps_1) == 2
    dep_ids_1 = {d["deployment_id"] for d in deps_1}
    assert dep_id_1 in dep_ids_1
    assert dep_id_2 in dep_ids_1

    # 5. List deployments for owner-2
    list_res_2 = client.get("/api/deployments", headers={"X-User-Id": "owner-2"})
    assert list_res_2.status_code == 200
    deps_2 = list_res_2.json()
    assert len(deps_2) == 1
    assert deps_2[0]["deployment_name"] == "dep-3"

    # 6. Fetch specific deployment by ID (owner-1)
    get_res_1 = client.get(f"/api/deployments/{dep_id_1}", headers={"X-User-Id": "owner-1"})
    assert get_res_1.status_code == 200
    assert get_res_1.json()["deployment_name"] == "dep-1"

    # 7. Attempt to fetch owner-2's deployment as owner-1 (should return 404)
    get_res_2 = client.get(f"/api/deployments/{res3.json()['deployment_id']}", headers={"X-User-Id": "owner-1"})
    assert get_res_2.status_code == 404


def test_delete_deployment_success(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create a task
    payload = {
        "task_name": "del-dep-task",
        "display_name": "Delete Dep Task",
        "input_schema": '{"type": "object"}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )

    # 2. Provision and wait for it to become ACTIVE
    mock_init = MagicMock(returncode=0, stdout="init ok", stderr="")
    mock_apply = MagicMock(returncode=0, stdout="apply ok", stderr="")
    mock_output = MagicMock(returncode=0, stdout='{}', stderr="")
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [mock_init, mock_apply, mock_output]
        res = client.post(
            "/api/provision/del-dep-task?deployment_name=dep-to-delete",
            json={},
            headers={"X-User-Id": "owner-1"}
        )
        assert res.status_code == 202
        dep_id = res.json()["deployment_id"]

        # Wait until ACTIVE
        db = TestSessionLocal()
        try:
            for _ in range(15):
                db.expire_all()
                dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
                if dep and dep.status == DeploymentStatus.ACTIVE:
                    break
                time.sleep(0.1)
            dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
            assert dep.status == DeploymentStatus.ACTIVE
        finally:
            db.close()

    # 3. Perform DELETE request and mock the terraform destroy command
    mock_destroy = MagicMock(returncode=0, stdout="destroy ok", stderr="")
    # Create the run dir manually so that worker doesn't exit early
    run_dir = settings.DEPLOYMENTS_ROOT / dep_id
    run_dir.mkdir(parents=True, exist_ok=True)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_destroy
        del_res = client.delete(
            f"/api/deployments/{dep_id}",
            headers={"X-User-Id": "owner-1"}
        )
        assert del_res.status_code == 202

        # Wait for deletion completion (should be removed from DB)
        db = TestSessionLocal()
        try:
            for _ in range(15):
                db.expire_all()
                dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
                if dep is None:
                    break
                time.sleep(0.1)
            dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
            assert dep is None
            assert not run_dir.exists()
        finally:
            db.close()


def test_delete_deployment_failure(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create task
    payload = {
        "task_name": "fail-del-task",
        "display_name": "Fail Delete Task",
        "input_schema": '{"type": "object"}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )

    # 2. Provision and wait until ACTIVE
    mock_init = MagicMock(returncode=0, stdout="init ok", stderr="")
    mock_apply = MagicMock(returncode=0, stdout="apply ok", stderr="")
    mock_output = MagicMock(returncode=0, stdout='{}', stderr="")
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [mock_init, mock_apply, mock_output]
        res = client.post(
            "/api/provision/fail-del-task?deployment_name=dep-fail-del",
            json={},
            headers={"X-User-Id": "owner-1"}
        )
        dep_id = res.json()["deployment_id"]

        db = TestSessionLocal()
        try:
            for _ in range(15):
                db.expire_all()
                dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
                if dep and dep.status == DeploymentStatus.ACTIVE:
                    break
                time.sleep(0.1)
        finally:
            db.close()

    # 3. Delete with mock destroy failure
    mock_destroy = MagicMock(returncode=1, stdout="destroy fail output", stderr="access denied")
    run_dir = settings.DEPLOYMENTS_ROOT / dep_id
    run_dir.mkdir(parents=True, exist_ok=True)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_destroy
        del_res = client.delete(
            f"/api/deployments/{dep_id}",
            headers={"X-User-Id": "owner-1"}
        )
        assert del_res.status_code == 202

        # Wait for worker completion (should change status to FAILED and populate last_error)
        db = TestSessionLocal()
        try:
            for _ in range(15):
                db.expire_all()
                dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
                if dep and dep.status == DeploymentStatus.FAILED:
                    break
                time.sleep(0.1)
            dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
            assert dep is not None
            assert dep.status == DeploymentStatus.FAILED
            assert "Terraform destroy failed" in dep.last_error
        finally:
            db.close()


def test_delete_deployment_unauthorized(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create task
    payload = {
        "task_name": "auth-del-task",
        "display_name": "Auth Delete Task",
        "input_schema": '{"type": "object"}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )

    # 2. Provision for owner-1
    mock_init = MagicMock(returncode=0, stdout="init ok", stderr="")
    mock_apply = MagicMock(returncode=0, stdout="apply ok", stderr="")
    mock_output = MagicMock(returncode=0, stdout='{}', stderr="")
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [mock_init, mock_apply, mock_output]
        res = client.post(
            "/api/provision/auth-del-task?deployment_name=dep-auth",
            json={},
            headers={"X-User-Id": "owner-1"}
        )
        dep_id = res.json()["deployment_id"]

    # 3. Attempt delete as owner-2 -> should return 404
    del_res = client.delete(
        f"/api/deployments/{dep_id}",
        headers={"X-User-Id": "owner-2"}
    )
    assert del_res.status_code == 404


def test_delete_deployment_invalid_state(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create task
    payload = {
        "task_name": "state-del-task",
        "display_name": "State Delete Task",
        "input_schema": '{"type": "object"}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )

    # 2. Provision but do not trigger/wait for worker to finish (status remains PROVISIONING)
    with patch("app.core.queue.MockArqRedis.enqueue_job", return_value=None):
        res = client.post(
            "/api/provision/state-del-task?deployment_name=dep-state",
            json={},
            headers={"X-User-Id": "owner-1"}
        )
        dep_id = res.json()["deployment_id"]

        # Attempt to delete -> 400 Bad Request
        del_res = client.delete(
            f"/api/deployments/{dep_id}",
            headers={"X-User-Id": "owner-1"}
        )
        assert del_res.status_code == 400
        assert "Cannot delete deployment in status" in del_res.json()["detail"]


def test_patch_deployment_success(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create task
    payload = {
        "task_name": "patch-task",
        "display_name": "Patch Task",
        "input_schema": '{"type": "object", "properties": {"param1": {"type": "string"}, "param2": {"type": "string"}}, "required": ["param1"]}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )

    # 2. Provision and wait until ACTIVE
    mock_init = MagicMock(returncode=0, stdout="init ok", stderr="")
    mock_apply = MagicMock(returncode=0, stdout="apply ok", stderr="")
    mock_output = MagicMock(returncode=0, stdout='{"out": {"value": "hello"}}', stderr="")
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [mock_init, mock_apply, mock_output]
        res = client.post(
            "/api/provision/patch-task?deployment_name=dep-patch",
            json={"param1": "val1"},
            headers={"X-User-Id": "owner-1"}
        )
        assert res.status_code == 202
        dep_id = res.json()["deployment_id"]

        db = TestSessionLocal()
        try:
            for _ in range(15):
                db.expire_all()
                dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
                if dep and dep.status == DeploymentStatus.ACTIVE:
                    break
                time.sleep(0.1)
            dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
            assert dep.status == DeploymentStatus.ACTIVE
            assert dep.current_inputs == {"param1": "val1"}
        finally:
            db.close()

    # 3. Patch deployment
    mock_init_patch = MagicMock(returncode=0, stdout="init patch ok", stderr="")
    mock_apply_patch = MagicMock(returncode=0, stdout="apply patch ok", stderr="")
    mock_output_patch = MagicMock(returncode=0, stdout='{"out": {"value": "updated"}}', stderr="")
    
    run_dir = settings.DEPLOYMENTS_ROOT / dep_id
    run_dir.mkdir(parents=True, exist_ok=True)

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [mock_init_patch, mock_apply_patch, mock_output_patch]
        patch_res = client.patch(
            f"/api/deployments/{dep_id}",
            json={"param2": "val2"},
            headers={"X-User-Id": "owner-1"}
        )
        assert patch_res.status_code == 202
        
        # Wait for update completion
        db = TestSessionLocal()
        try:
            for _ in range(15):
                db.expire_all()
                dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
                if dep and dep.status == DeploymentStatus.ACTIVE:
                    break
                time.sleep(0.1)
            dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
            assert dep.status == DeploymentStatus.ACTIVE
            assert dep.current_inputs == {"param1": "val1", "param2": "val2"}
            assert dep.outputs == {"out": "updated"}
        finally:
            db.close()


def test_patch_deployment_validation_failure(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create task
    payload = {
        "task_name": "patch-fail-task",
        "display_name": "Patch Fail Task",
        "input_schema": '{"type": "object", "properties": {"param1": {"type": "string"}}, "required": ["param1"]}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )

    # 2. Provision and wait until ACTIVE
    mock_init = MagicMock(returncode=0, stdout="init ok", stderr="")
    mock_apply = MagicMock(returncode=0, stdout="apply ok", stderr="")
    mock_output = MagicMock(returncode=0, stdout='{}', stderr="")
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [mock_init, mock_apply, mock_output]
        res = client.post(
            "/api/provision/patch-fail-task?deployment_name=dep-patch-fail",
            json={"param1": "val1"},
            headers={"X-User-Id": "owner-1"}
        )
        dep_id = res.json()["deployment_id"]

        db = TestSessionLocal()
        try:
            for _ in range(15):
                db.expire_all()
                dep = db.query(Deployment).filter(Deployment.deployment_id == dep_id).first()
                if dep and dep.status == DeploymentStatus.ACTIVE:
                    break
                time.sleep(0.1)
        finally:
            db.close()

    # 3. Patch deployment with invalid type (param1 should be string)
    patch_res = client.patch(
        f"/api/deployments/{dep_id}",
        json={"param1": 123},
        headers={"X-User-Id": "owner-1"}
    )
    assert patch_res.status_code == 422
    assert "combined inputs failed schema validation" in patch_res.json()["detail"]


def test_patch_deployment_invalid_state(client):
    headers = {"X-Admin-Token": "admin-token"}
    
    # 1. Create task
    payload = {
        "task_name": "patch-state-task",
        "display_name": "Patch State Task",
        "input_schema": '{"type": "object"}',
    }
    client.post(
        "/api/admin/tasks",
        data=payload,
        files={"script": ("main.tf", io.BytesIO(b""), "text/plain")},
        headers=headers
    )

    # 2. Provision but do not wait for completion (stays PROVISIONING)
    with patch("app.core.queue.MockArqRedis.enqueue_job", return_value=None):
        res = client.post(
            "/api/provision/patch-state-task?deployment_name=dep-patch-state",
            json={},
            headers={"X-User-Id": "owner-1"}
        )
        dep_id = res.json()["deployment_id"]

    # 3. Attempt PATCH -> 400 Bad Request
    patch_res = client.patch(
        f"/api/deployments/{dep_id}",
        json={},
        headers={"X-User-Id": "owner-1"}
    )
    assert patch_res.status_code == 400
    assert "Cannot update deployment in status" in patch_res.json()["detail"]
