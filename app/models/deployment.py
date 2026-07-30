import enum
from sqlalchemy import Column, DateTime, Enum, String, JSON, func
from app.core.database import Base

class DeploymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    UPDATING = "UPDATING"
    DESTROYING = "DESTROYING"
    DESTROYED = "DESTROYED"
    FAILED = "FAILED"


class Deployment(Base):
    __tablename__ = "deployments"

    deployment_id = Column(String, primary_key=True)
    deployment_name = Column(String, nullable=False)
    task_name = Column(String, nullable=False)          # FK -> tasks.task_name
    owner_id = Column(String, nullable=False, index=True)
    status = Column(Enum(DeploymentStatus), nullable=False, default=DeploymentStatus.PENDING)
    state_path = Column(String, nullable=True)
    current_inputs = Column(JSON, nullable=False)
    outputs = Column(JSON, nullable=True)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
