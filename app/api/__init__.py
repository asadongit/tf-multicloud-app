from app.api.admin import router as admin_router
from app.api.tasks import router as tasks_router
from app.api.deployments import router as deployments_router

__all__ = ["admin_router", "tasks_router", "deployments_router"]
