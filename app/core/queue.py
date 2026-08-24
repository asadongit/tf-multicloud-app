import os
import asyncio
from arq.connections import create_pool, ArqRedis
from arq.connections import RedisSettings
from app.core.config import settings

_arq_pool = None

class MockArqRedis:
    def __init__(self):
        self.jobs = []
        self.hashes = {}
        self.kv = {}

    async def get(self, name: str):
        val = self.kv.get(name)
        if val is None:
            return None
        if isinstance(val, str):
            return val.encode()
        return val

    async def set(self, name: str, value: str, ex: int = None) -> bool:
        self.kv[name] = value
        return True

    async def setex(self, name: str, time: int, value: str) -> bool:
        self.kv[name] = value
        return True

    async def delete(self, *names: str) -> int:
        count = 0
        for n in names:
            if n in self.kv:
                del self.kv[n]
                count += 1
        return count


    async def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        if name not in self.hashes:
            self.hashes[name] = {}
        curr = self.hashes[name].get(key, 0)
        new_val = curr + amount
        self.hashes[name][key] = new_val
        return new_val

    async def hdel(self, name: str, *keys: str) -> int:
        count = 0
        if name in self.hashes:
            for k in keys:
                if k in self.hashes[name]:
                    del self.hashes[name][k]
                    count += 1
        return count

    async def hkeys(self, name: str) -> list:
        if name in self.hashes:
            return list(self.hashes[name].keys())
        return []

    async def hset(self, name: str, key: str = None, value: str = None, mapping: dict = None) -> int:
        if name not in self.hashes:
            self.hashes[name] = {}
        count = 0
        if mapping:
            for k, v in mapping.items():
                if k not in self.hashes[name]:
                    count += 1
                self.hashes[name][k] = int(v)
        elif key is not None:
            if key not in self.hashes[name]:
                count += 1
            self.hashes[name][key] = int(value) if value is not None else value
        return count

    async def exists(self, *names: str) -> int:
        count = 0
        for n in names:
            if n in self.hashes and len(self.hashes[n]) > 0:
                count += 1
        return count

    def _run_async_worker(self, coro_func, *args, **kwargs):
        asyncio.run(coro_func(*args, **kwargs))

    async def enqueue_job(self, function_name: str, *args, **kwargs):
        self.jobs.append((function_name, args, kwargs))
        print(f"[MockArqRedis] Enqueued job: '{function_name}' with args={args} kwargs={kwargs}")
        if function_name == "run_terraform_create":
            # Dynamically import to prevent circular dependency
            from app.worker import run_terraform_create
            # Spawn task to run asynchronously in a separate thread
            asyncio.create_task(asyncio.to_thread(
                self._run_async_worker,
                run_terraform_create,
                None,
                kwargs.get("run_id"),
                kwargs.get("deployment_id"),
                kwargs.get("task_name"),
                kwargs.get("module_source"),
                kwargs.get("inputs")
            ))
        elif function_name == "run_terraform_destroy":
            # Dynamically import to prevent circular dependency
            from app.worker import run_terraform_destroy
            # Spawn task to run asynchronously in a separate thread
            asyncio.create_task(asyncio.to_thread(
                self._run_async_worker,
                run_terraform_destroy,
                None,
                kwargs.get("run_id"),
                kwargs.get("deployment_id")
            ))
        elif function_name == "run_terraform_update":
            # Dynamically import to prevent circular dependency
            from app.worker import run_terraform_update
            # Spawn task to run asynchronously in a separate thread
            asyncio.create_task(asyncio.to_thread(
                self._run_async_worker,
                run_terraform_update,
                None,
                kwargs.get("run_id"),
                kwargs.get("deployment_id"),
                kwargs.get("inputs")
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
