import os
import asyncio
from arq.connections import create_pool, ArqRedis
from arq.connections import RedisSettings
from app.core.config import settings

_arq_pool = None

class MockArqRedis:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, function_name: str, *args, **kwargs):
        self.jobs.append((function_name, args, kwargs))
        print(f"[MockArqRedis] Enqueued job: '{function_name}' with args={args} kwargs={kwargs}")
        if function_name == "run_terraform_create":
            # Dynamically import to prevent circular dependency
            from app.worker import run_terraform_create
            # Spawn task to run asynchronously in-process
            asyncio.create_task(run_terraform_create(
                ctx=None,
                run_id=kwargs.get("run_id"),
                deployment_id=kwargs.get("deployment_id"),
                task_name=kwargs.get("task_name"),
                module_source=kwargs.get("module_source"),
                inputs=kwargs.get("inputs")
            ))
        elif function_name == "run_terraform_destroy":
            # Dynamically import to prevent circular dependency
            from app.worker import run_terraform_destroy
            # Spawn task to run asynchronously in-process
            asyncio.create_task(run_terraform_destroy(
                ctx=None,
                run_id=kwargs.get("run_id"),
                deployment_id=kwargs.get("deployment_id")
            ))
        elif function_name == "run_terraform_update":
            # Dynamically import to prevent circular dependency
            from app.worker import run_terraform_update
            # Spawn task to run asynchronously in-process
            asyncio.create_task(run_terraform_update(
                ctx=None,
                run_id=kwargs.get("run_id"),
                deployment_id=kwargs.get("deployment_id"),
                inputs=kwargs.get("inputs")
            ))
        return None

async def init_arq_pool():
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool

    redis_host = settings.REDIS_HOST
    redis_port = settings.REDIS_PORT
    
    # Configure low timeout and no retries to fail fast if Redis is not running
    redis_settings = RedisSettings(
        host=redis_host, 
        port=redis_port, 
        conn_timeout=1, 
        conn_retries=0
    )
    try:
        pool = await create_pool(redis_settings)
        await pool.ping()
        _arq_pool = pool
        print(f"Successfully connected to Redis at {redis_host}:{redis_port}")
    except Exception as e:
        print(f"Could not connect to Redis at {redis_host}:{redis_port}. Falling back to MockArqRedis. (Error: {e})")
        _arq_pool = MockArqRedis()
    return _arq_pool

async def get_arq_pool():
    global _arq_pool
    if _arq_pool is None:
        await init_arq_pool()
    return _arq_pool
