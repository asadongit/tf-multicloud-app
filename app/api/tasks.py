from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.task import Task
from app.schemas.task import TaskResponse

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks", response_model=list[TaskResponse])
def list_tasks(
    db: Session = Depends(get_db),
):
    return db.query(Task).all()


@router.get("/tasks/{task_name}", response_model=TaskResponse)
def get_task(
    task_name: str,
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.task_name == task_name).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
