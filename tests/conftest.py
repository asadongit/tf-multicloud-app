import io
import os
import shutil
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup test environment variables before importing app
os.environ["TASK_SCRIPTS_ROOT"] = "./test_task_scripts"
os.environ["DEPLOYMENTS_ROOT"] = "./test_deployments_runs"
os.environ["TESTING"] = "true"

from app.main import app as fastapi_app
from app.core.database import Base, get_db
from app.core.queue import get_arq_pool, MockArqRedis
from app.models.task import Task
from app.models.deployment import Deployment
from app.core.config import settings

TEST_DATABASE_URL = "sqlite:///./test_tasks.db"

test_engine = create_engine(
    TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Patch the worker database session local
from app import worker as app_worker
app_worker.SessionLocal = TestSessionLocal


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


mock_redis = MockArqRedis()

@pytest.fixture(scope="session")
def client():
    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_arq_pool] = lambda: mock_redis
    
    with TestClient(fastapi_app) as c:
        yield c
        
    fastapi_app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def setup_and_teardown():
    # Drop and recreate tables to ensure schema matches model changes
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    
    yield
    
    # Clean up DB after test run
    db = TestSessionLocal()
    try:
        db.query(Task).delete()
        db.query(Deployment).delete()
        db.commit()
    finally:
        db.close()
        
    # Clean up uploaded scripts
    if settings.TASK_SCRIPTS_ROOT.exists():
        try:
            shutil.rmtree(settings.TASK_SCRIPTS_ROOT)
        except PermissionError:
            # On Windows, sometimes file locks are not cleared immediately
            pass

    # Clean up test deployments runs
    if settings.DEPLOYMENTS_ROOT.exists():
        try:
            shutil.rmtree(settings.DEPLOYMENTS_ROOT)
        except PermissionError:
            pass
            
    # Clean up test database file if created
    if os.path.exists("./test_tasks.db"):
        try:
            os.remove("./test_tasks.db")
        except PermissionError:
            pass
