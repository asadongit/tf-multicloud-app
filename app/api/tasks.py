from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.task import Task
from app.schemas.task import TaskResponse, TaskSummaryResponse

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks", response_model=list[TaskResponse] | list[TaskSummaryResponse])
def list_tasks(
    view: str = Query(None, description="Set to 'summary' to retrieve a reduced view"),
    category: str = Query(None, description="Filter tasks by category"),
    provider: str = Query(None, description="Filter tasks by provider"),
    db: Session = Depends(get_db),
):
    query = db.query(Task)
    if category:
        query = query.filter(Task.category == category)
    if provider:
        query = query.filter(Task.provider == provider)

    from sqlalchemy.orm import load_only

    if view == "summary":
        tasks = query.options(load_only(Task.task_name, Task.description, Task.display_name, Task.category, Task.provider)).all()
        return [TaskSummaryResponse.model_validate(t) for t in tasks]
    else:
        tasks = query.all()
        return tasks
    
    #tasks = query.all()
    #if view == "summary":
    #    return [TaskSummaryResponse.model_validate(t) for t in tasks]
    #return tasks


@router.get("/tasks/{task_name}", response_model=TaskResponse)
def get_task(
    task_name: str,
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.task_name == task_name).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
