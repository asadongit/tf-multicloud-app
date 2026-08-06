import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.database import Base, engine
from app.api.admin import router as admin_router
from app.api.tasks import router as tasks_router
from app.api.deployments import router as deployments_router
from app.api.chat import router as chat_router
from app.frontend.router import router as frontend_router
from app.core.queue import init_arq_pool
from app.mcp_server import mcp

from sqlalchemy import func
from app.core.database import SessionLocal
from app.models.task import Task
from app.core.queue import init_arq_pool, get_arq_pool

# Create database tables
Base.metadata.create_all(bind=engine)

async def bootstrap_distinct_counts():
    """Seeds Redis distinct hashes from database ground truth on cold startup if missing."""
    try:
        redis = await get_arq_pool()
        cat_exists = await redis.exists("categories:distinct")
        prov_exists = await redis.exists("providers:distinct")
        
        if not cat_exists or not prov_exists:
            db = SessionLocal()
            try:
                if not cat_exists:
                    cat_rows = db.query(Task.category, func.count(Task.task_name))\
                        .filter(Task.category.isnot(None))\
                        .group_by(Task.category).all()
                    cat_counts = {val: count for val, count in cat_rows if val}
                    if cat_counts:
                        await redis.hset("categories:distinct", mapping=cat_counts)
                
                if not prov_exists:
                    prov_rows = db.query(Task.provider, func.count(Task.task_name))\
                        .filter(Task.provider.isnot(None))\
                        .group_by(Task.provider).all()
                    prov_counts = {val: count for val, count in prov_rows if val}
                    if prov_counts:
                        await redis.hset("providers:distinct", mapping=prov_counts)
            finally:
                db.close()
    except Exception as exc:
        print(f"[Warning] Failed to bootstrap Redis distinct counts: {exc}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize connection pool on startup
    await init_arq_pool()
    await bootstrap_distinct_counts()
    yield

app = FastAPI(title="Task Registry Admin API", lifespan=lifespan)

# Mount static assets
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register API Routers
app.include_router(admin_router)
app.include_router(tasks_router)
app.include_router(deployments_router)
app.include_router(chat_router)

# Register HTML Frontend Router
app.include_router(frontend_router)

# Mount the MCP server to /mcp route
app.mount("/mcp", mcp.http_app())

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, reload=True)
