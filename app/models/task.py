from sqlalchemy import Column, DateTime, String, func, JSON
from app.core.database import Base

class Task(Base):
    __tablename__ = "tasks"

    task_name = Column(String, primary_key=True)
    display_name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    input_schema = Column(JSON, nullable=False)
    module_source = Column(String, nullable=False)
    module_version = Column(String, nullable=True)
    category = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
