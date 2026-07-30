import uuid
from typing import Optional
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, status, Body, Header, Query
from jsonschema import validate as jsonschema_validate
from jsonschema.exceptions import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user, require_admin
from app.core.queue import get_arq_pool
from app.models.task import Task
from app.models.deployment import Deployment, DeploymentStatus
from app.schemas.deployment import ProvisionResponse, DeploymentResponse

router = APIRouter(prefix="/api", tags=["deployments"])


@router.post(
    "/provision/{task_name}",
    response_model=ProvisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def provision_task(
    task_name: str,
    deployment_name: str,
    payload: dict = Body(..., description="Must satisfy the task's input_schema"),
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_user),
    redis: ArqRedis = Depends(get_arq_pool),
):
    task = db.query(Task).filter(Task.task_name == task_name).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_name}' not found")

    # Validate the payload against this task's input_schema
    try:
        jsonschema_validate(instance=payload, schema=task.input_schema)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"inputs failed schema validation: {exc.message}",
        )

    # block duplicate deployment names per owner
    existing = (
        db.query(Deployment)
        .filter(Deployment.owner_id == owner_id, Deployment.deployment_name == deployment_name)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"You already have a deployment named '{deployment_name}'",
        )

    deployment_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    deployment = Deployment(
        deployment_id=deployment_id,
        deployment_name=deployment_name,
        task_name=task_name,
        owner_id=owner_id,
        status=DeploymentStatus.PENDING,
        current_inputs=payload,
    )

    try:
        db.add(deployment)
        db.commit()
        db.refresh(deployment)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create deployment: {exc}")

    try:
        await redis.enqueue_job(
            "run_terraform_create",
            run_id=run_id,
            deployment_id=deployment_id,
            task_name=task_name,
            module_source=task.module_source,
            inputs=payload,
        )
    except Exception as exc:
        deployment.status = DeploymentStatus.FAILED
        deployment.last_error = f"Failed to enqueue job: {exc}"
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to queue provisioning job")

    deployment.status = DeploymentStatus.PROVISIONING
    db.commit()
    db.refresh(deployment)

    return ProvisionResponse(
        run_id=run_id,
        deployment_id=deployment.deployment_id,
        deployment_name=deployment.deployment_name,
        task_name=deployment.task_name,
        status=deployment.status,
    )


@router.get("/deployments", response_model=list[DeploymentResponse])
def list_deployments(
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_user),
):
    return db.query(Deployment).filter(Deployment.owner_id == owner_id).all()


@router.get("/deployments/all", response_model=list[DeploymentResponse])
def list_all_deployments(
    db: Session = Depends(get_db)
):
    """Retrieve all deployments globally, across all owners."""
    return db.query(Deployment).all()


@router.get("/deployments/all/{deployment_id}", response_model=DeploymentResponse)
def get_deployment_global(
    deployment_id: str,
    db: Session = Depends(get_db)
):
    """Retrieve a single deployment globally by ID, across all owners."""
    deployment = db.query(Deployment).filter(Deployment.deployment_id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment


@router.get("/deployments/all/name/{deployment_name}", response_model=list[DeploymentResponse])
def get_deployments_by_name_global(
    deployment_name: str,
    db: Session = Depends(get_db)
):
    """Retrieve all deployments matching the given name globally, across all users."""
    deployments = db.query(Deployment).filter(Deployment.deployment_name == deployment_name).all()
    return deployments


@router.get("/deployments/name/{deployment_name}", response_model=DeploymentResponse)
def get_deployment_by_name(
    deployment_name: str,
    target_user: Optional[str] = Query(None, description="Owner ID of the target user for cross-user lookup"),
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_user),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
):
    """Retrieve a single deployment by its unique name for the authenticated user, or another user if privileged."""
    if target_user and target_user != owner_id:
        # Cross-user lookup: require admin token or privileged role
        is_admin = (x_admin_token == "admin-token")
        is_privileged = (x_user_role in ["admin", "privileged"])
        if not (is_admin or is_privileged):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to view other users' deployments."
            )
        lookup_user = target_user
    else:
        lookup_user = owner_id

    deployment = db.query(Deployment).filter(
        Deployment.deployment_name == deployment_name,
        Deployment.owner_id == lookup_user
    ).first()
    if not deployment:
        raise HTTPException(
            status_code=404,
            detail=f"Deployment with name '{deployment_name}' not found for user '{lookup_user}'."
        )
    return deployment


@router.get("/deployments/{deployment_id}", response_model=DeploymentResponse)
def get_deployment(
    deployment_id: str,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_user),
):
    deployment = db.query(Deployment).filter(
        Deployment.deployment_id == deployment_id,
        Deployment.owner_id == owner_id
    ).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment


@router.delete("/deployments/name/{deployment_name}", status_code=status.HTTP_202_ACCEPTED)
async def delete_deployment_by_name(
    deployment_name: str,
    target_user: Optional[str] = Query(None, description="Owner ID of the target user for cross-user lookup"),
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_user),
    redis: ArqRedis = Depends(get_arq_pool),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
):
    """Initiate teardown and deletion of a deployment by its unique name."""
    if target_user and target_user != owner_id:
        # Cross-user check: require admin token or privileged role
        is_admin = (x_admin_token == "admin-token")
        is_privileged = (x_user_role in ["admin", "privileged"])
        if not (is_admin or is_privileged):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete other users' deployments."
            )
        lookup_user = target_user
    else:
        lookup_user = owner_id

    deployment = db.query(Deployment).filter(
        Deployment.deployment_name == deployment_name,
        Deployment.owner_id == lookup_user
    ).first()

    if not deployment:
        raise HTTPException(
            status_code=404,
            detail=f"Deployment with name '{deployment_name}' not found for user '{lookup_user}'."
        )

    # Prevent deleting deployments in the middle of standard operations
    if deployment.status in [
        DeploymentStatus.PENDING,
        DeploymentStatus.PROVISIONING,
        DeploymentStatus.DESTROYING,
        DeploymentStatus.UPDATING
    ]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete deployment in status '{deployment.status.value}'"
        )

    run_id = str(uuid.uuid4())
    original_status = deployment.status

    deployment.status = DeploymentStatus.DESTROYING
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update deployment status: {exc}")

    try:
        await redis.enqueue_job(
            "run_terraform_destroy",
            run_id=run_id,
            deployment_id=deployment.deployment_id,
        )
    except Exception as exc:
        deployment.status = original_status
        deployment.last_error = f"Failed to enqueue destroy job: {exc}"
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to queue destroy job")

    return {"detail": "Teardown initiated", "run_id": run_id}


@router.delete("/deployments/{deployment_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_deployment(
    deployment_id: str,
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_user),
    redis: ArqRedis = Depends(get_arq_pool),
):
    deployment = db.query(Deployment).filter(
        Deployment.deployment_id == deployment_id,
        Deployment.owner_id == owner_id
    ).first()

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Prevent deleting deployments in the middle of standard operations
    if deployment.status in [
        DeploymentStatus.PENDING,
        DeploymentStatus.PROVISIONING,
        DeploymentStatus.DESTROYING,
        DeploymentStatus.UPDATING
    ]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete deployment in status '{deployment.status.value}'"
        )

    run_id = str(uuid.uuid4())
    original_status = deployment.status

    deployment.status = DeploymentStatus.DESTROYING
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update deployment status: {exc}")

    try:
        await redis.enqueue_job(
            "run_terraform_destroy",
            run_id=run_id,
            deployment_id=deployment_id,
        )
    except Exception as exc:
        deployment.status = original_status
        deployment.last_error = f"Failed to enqueue destroy job: {exc}"
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to queue destroy job")

    return {"detail": "Teardown initiated", "run_id": run_id}


@router.patch(
    "/deployments/name/{deployment_name}",
    response_model=ProvisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def patch_deployment_by_name(
    deployment_name: str,
    target_user: Optional[str] = Query(None, description="Owner ID of the target user for cross-user lookup"),
    payload: dict = Body(..., description="Only variables to update"),
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_user),
    redis: ArqRedis = Depends(get_arq_pool),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
):
    """Update variables and initiate apply update of a deployment by its unique name."""
    if target_user and target_user != owner_id:
        # Cross-user check: require admin token or privileged role
        is_admin = (x_admin_token == "admin-token")
        is_privileged = (x_user_role in ["admin", "privileged"])
        if not (is_admin or is_privileged):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update other users' deployments."
            )
        lookup_user = target_user
    else:
        lookup_user = owner_id

    deployment = db.query(Deployment).filter(
        Deployment.deployment_name == deployment_name,
        Deployment.owner_id == lookup_user
    ).first()

    if not deployment:
        raise HTTPException(
            status_code=404,
            detail=f"Deployment with name '{deployment_name}' not found for user '{lookup_user}'."
        )

    # Prevent patching deployments in the middle of standard operations
    if deployment.status in [
        DeploymentStatus.PENDING,
        DeploymentStatus.PROVISIONING,
        DeploymentStatus.DESTROYING,
        DeploymentStatus.UPDATING
    ]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update deployment in status '{deployment.status.value}'"
        )

    task = db.query(Task).filter(Task.task_name == deployment.task_name).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{deployment.task_name}' not found")

    # Combine existing current_inputs with the new payload
    combined_inputs = {**deployment.current_inputs, **payload}

    # Validate combined inputs against task input_schema
    try:
        jsonschema_validate(instance=combined_inputs, schema=task.input_schema)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"combined inputs failed schema validation: {exc.message}",
        )

    run_id = str(uuid.uuid4())
    original_status = deployment.status
    original_inputs = deployment.current_inputs

    # Update state in DB
    deployment.status = DeploymentStatus.UPDATING
    deployment.current_inputs = combined_inputs

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update deployment: {exc}")

    try:
        await redis.enqueue_job(
            "run_terraform_update",
            run_id=run_id,
            deployment_id=deployment.deployment_id,
            inputs=combined_inputs,
        )
    except Exception as exc:
        deployment.status = original_status
        deployment.current_inputs = original_inputs
        deployment.last_error = f"Failed to enqueue update job: {exc}"
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to queue update job")

    return ProvisionResponse(
        run_id=run_id,
        deployment_id=deployment.deployment_id,
        deployment_name=deployment.deployment_name,
        task_name=deployment.task_name,
        status=deployment.status,
    )


@router.patch(
    "/deployments/{deployment_id}",
    response_model=ProvisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def patch_deployment(
    deployment_id: str,
    payload: dict = Body(..., description="Only variables to update"),
    db: Session = Depends(get_db),
    owner_id: str = Depends(get_current_user),
    redis: ArqRedis = Depends(get_arq_pool),
):
    deployment = db.query(Deployment).filter(
        Deployment.deployment_id == deployment_id,
        Deployment.owner_id == owner_id
    ).first()

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Prevent patching deployments in the middle of standard operations
    if deployment.status in [
        DeploymentStatus.PENDING,
        DeploymentStatus.PROVISIONING,
        DeploymentStatus.DESTROYING,
        DeploymentStatus.UPDATING
    ]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update deployment in status '{deployment.status.value}'"
        )

    task = db.query(Task).filter(Task.task_name == deployment.task_name).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{deployment.task_name}' not found")

    # Combine existing current_inputs with the new payload
    combined_inputs = {**deployment.current_inputs, **payload}

    # Validate combined inputs against task input_schema
    try:
        jsonschema_validate(instance=combined_inputs, schema=task.input_schema)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"combined inputs failed schema validation: {exc.message}",
        )

    run_id = str(uuid.uuid4())
    original_status = deployment.status
    original_inputs = deployment.current_inputs

    # Update state in DB
    deployment.status = DeploymentStatus.UPDATING
    deployment.current_inputs = combined_inputs

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update deployment: {exc}")

    try:
        await redis.enqueue_job(
            "run_terraform_update",
            run_id=run_id,
            deployment_id=deployment_id,
            inputs=combined_inputs,
        )
    except Exception as exc:
        deployment.status = original_status
        deployment.current_inputs = original_inputs
        deployment.last_error = f"Failed to enqueue update job: {exc}"
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to queue update job")

    return ProvisionResponse(
        run_id=run_id,
        deployment_id=deployment.deployment_id,
        deployment_name=deployment.deployment_name,
        task_name=deployment.task_name,
        status=deployment.status,
    )
