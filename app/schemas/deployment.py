from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from app.models.deployment import DeploymentStatus

class ProvisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    deployment_id: str
    deployment_name: str
    task_name: str
    status: DeploymentStatus


class DeploymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    deployment_id: str
    deployment_name: str
    task_name: str
    owner_id: str
    status: DeploymentStatus
    current_inputs: dict
    outputs: Optional[dict]
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime
