from pydantic import BaseModel, ConfigDict
from typing import Optional

class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_name: str
    display_name: str
    description: Optional[str]
    input_schema: dict
    module_source: str
    module_version: Optional[str]
    category: Optional[str]
    provider: Optional[str]
