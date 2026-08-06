from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.task import Task
from app.models.deployment import Deployment

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def index_page(request: Request, db: Session = Depends(get_db)):
    tasks = db.query(Task).order_by(Task.created_at.desc()).all()
    deployments = db.query(Deployment).order_by(Deployment.created_at.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "tasks": tasks,
            "deployments": deployments,
            "active_page": "dashboard"
        }
    )


@router.get("/tasks/new", response_class=HTMLResponse)
def new_task_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="new_task.html",
        context={
            "active_page": "new_task"
        }
    )


@router.get("/deployments/{deployment_id}", response_class=HTMLResponse)
def deployment_detail_page(request: Request, deployment_id: str, db: Session = Depends(get_db)):
    deployment = db.query(Deployment).filter(Deployment.deployment_id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    task = db.query(Task).filter(Task.task_name == deployment.task_name).first()
    return templates.TemplateResponse(
        request=request,
        name="deployment_detail.html",
        context={
            "deployment": deployment,
            "task": task,
            "active_page": "dashboard"
        }
    )


@router.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context={
            "active_page": "chat"
        }
    )

