import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.database import Base, engine
from app.api.admin import router as admin_router
from app.api.tasks import router as tasks_router
from app.api.deployments import router as deployments_router
from app.frontend.router import router as frontend_router
from app.core.queue import init_arq_pool
from app.mcp_server import mcp

# Create database tables
Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize connection pool on startup
    await init_arq_pool()
    yield

app = FastAPI(title="Task Registry Admin API", lifespan=lifespan)

# Mount static assets
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register API Routers
app.include_router(admin_router)
app.include_router(tasks_router)
app.include_router(deployments_router)

# Register HTML Frontend Router
app.include_router(frontend_router)

# Mount the MCP server to /mcp route
app.mount("/mcp", mcp.sse_app())

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, reload=True)
