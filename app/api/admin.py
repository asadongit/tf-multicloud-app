import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional, Any
import hcl2

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import require_admin
from app.core.config import settings
from app.models.task import Task
from app.models.deployment import Deployment
from app.schemas.task import TaskResponse
from app.core.queue import get_arq_pool

router = APIRouter(prefix="/api", tags=["admin"])

ALLOWED_EXTENSIONS = {".tf", ".zip"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _validate_input_schema(raw: str) -> dict:
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"input_schema is not valid JSON: {exc}")

    try:
        Draft7Validator.check_schema(schema)
    except SchemaError as exc:
        raise HTTPException(status_code=422, detail=f"input_schema is not a valid JSON Schema: {exc.message}")

    return schema


def _strip_quotes(val: Any) -> Any:
    if isinstance(val, str):
        if val.startswith('"') and val.endswith('"'):
            return val[1:-1]
        if val.startswith("'") and val.endswith("'"):
            return val[1:-1]
    return val


def _parse_tf_type_to_jsonschema(raw_type: str) -> dict:
    """
    Parses a raw Terraform type string (as output by hcl2) into a JSON Schema.
    e.g., '${map(object({priority = number}))}' -> {"type": "object", "additionalProperties": ...}
    """
    if not isinstance(raw_type, str):
        return {"type": "string"}
        
    s = raw_type.strip()
    
    # Remove ${...} wrapper if present
    if s.startswith("${") and s.endswith("}"):
        s = s[2:-1].strip()
        
    if s == "string":
        return {"type": "string"}
    if s == "number":
        return {"type": "number"}
    if s == "bool" or s == "boolean":
        return {"type": "boolean"}
    if s == "any":
        return {}
        
    def _extract_between(text, open_char, close_char):
        start = text.find(open_char)
        if start == -1: return ""
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_char:
                depth += 1
            elif text[i] == close_char:
                depth -= 1
                if depth == 0:
                    return text[start+1:i].strip()
        return ""
        
    def _split_fields(text):
        fields = []
        depth = 0
        current = []
        for char in text:
            if char in "({[": depth += 1
            elif char in ")}]": depth -= 1
            
            if char == "," and depth == 0:
                fields.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        if current:
            val = "".join(current).strip()
            if val:
                fields.append(val)
        return fields

    if s.startswith("list(") or s.startswith("set("):
        inner = _extract_between(s, "(", ")")
        schema = {"type": "array", "items": _parse_tf_type_to_jsonschema(inner)}
        if s.startswith("set("):
            schema["uniqueItems"] = True
        return schema
        
    if s.startswith("map("):
        inner = _extract_between(s, "(", ")")
        return {"type": "object", "additionalProperties": _parse_tf_type_to_jsonschema(inner)}
        
    if s.startswith("object("):
        inner = _extract_between(s, "{", "}")
        fields = _split_fields(inner)
        properties = {}
        required = []
        
        for field in fields:
            if "=" not in field:
                continue
            idx = field.find("=")
            k = field[:idx].strip()
            v = field[idx+1:].strip()
            
            if v.startswith("optional("):
                opt_inner = _extract_between(v, "(", ")")
                opt_parts = _split_fields(opt_inner)
                if opt_parts:
                    properties[k] = _parse_tf_type_to_jsonschema(opt_parts[0])
                    if len(opt_parts) > 1:
                        def_val = opt_parts[1]
                        try:
                            properties[k]["default"] = json.loads(def_val)
                        except json.JSONDecodeError:
                            properties[k]["default"] = _strip_quotes(def_val)
            else:
                properties[k] = _parse_tf_type_to_jsonschema(v)
                required.append(k)
                
        schema = {"type": "object", "properties": properties, "additionalProperties": False}
        if required:
            schema["required"] = required
        return schema
        
    if s.startswith("tuple("):
        inner = _extract_between(s, "[", "]")
        elements = _split_fields(inner)
        items_schema = [_parse_tf_type_to_jsonschema(e) for e in elements]
        return {
            "type": "array", 
            "items": items_schema, 
            "minItems": len(items_schema), 
            "maxItems": len(items_schema)
        }
        
    return {"type": "string"}


def _generate_schema_from_tf(module_source: str) -> dict:
    path = Path(module_source)
    tf_files = []
    
    if path.is_file():
        if path.suffix == ".tf":
            tf_files.append(path)
    elif path.is_dir():
        tf_files = list(path.glob("**/*.tf"))
        
    properties = {}
    required = []
    
    for tf_file in tf_files:
        try:
            with open(tf_file, "r", encoding="utf-8") as f:
                parsed = hcl2.load(f)
        except Exception as e:
            print(f"[Warning] Failed to parse {tf_file} with hcl2: {e}")
            continue
            
        variables = parsed.get("variable", [])
        
        for var_block in variables:
            for var_name_raw, var_attrs in var_block.items():
                var_name = _strip_quotes(var_name_raw)
                var_props = {}
                
                # Type mapping
                tf_type = var_attrs.get("type", "string")
                if isinstance(tf_type, list) and len(tf_type) > 0:
                    tf_type_str = str(tf_type[0])
                else:
                    tf_type_str = str(tf_type)
                
                parsed_schema = _parse_tf_type_to_jsonschema(tf_type_str)
                var_props.update(parsed_schema)
                    
                # Description
                if "description" in var_attrs:
                    desc = var_attrs["description"]
                    if isinstance(desc, list) and len(desc) > 0:
                        var_props["description"] = _strip_quotes(desc[0])
                    else:
                        var_props["description"] = _strip_quotes(desc)
                        
                # Default
                if "default" in var_attrs:
                    default_val = var_attrs["default"]
                    if isinstance(default_val, list) and len(default_val) > 0:
                        val = default_val[0]
                    else:
                        val = default_val
                    
                    if isinstance(val, str):
                        var_props["default"] = _strip_quotes(val)
                    else:
                        var_props["default"] = val
                    
                    # Optional: Adjust type if default is null
                    if val is None and "type" in var_props:
                        if isinstance(var_props["type"], str):
                            var_props["type"] = [var_props["type"], "null"]
                        elif isinstance(var_props["type"], list) and "null" not in var_props["type"]:
                            var_props["type"].append("null")
                else:
                    required.append(var_name)
                    
                properties[var_name] = var_props
                
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": properties,
        "additionalProperties": False
    }
    
    if required:
        schema["required"] = required
        
    # Optional: validate the generated schema programmatically
    try:
        Draft7Validator.check_schema(schema)
    except SchemaError as exc:
        raise HTTPException(status_code=500, detail=f"Generated schema is invalid: {exc.message}")
        
    return schema


def _save_script(task_name: str, upload: UploadFile) -> str:
    """
    Persists the uploaded script under settings.TASK_SCRIPTS_ROOT/{task_name}/ and
    returns the resulting module path.
    """
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{suffix}'. Use .tf or .zip")

    task_dir = settings.TASK_SCRIPTS_ROOT / task_name
    try:
        task_dir.mkdir(parents=True, exist_ok=False)  # task_name is fresh, dir must not exist
    except FileExistsError:
        raise HTTPException(
            status_code=409,
            detail=f"Task script directory '{task_name}' already exists on disk. Please delete it manually or use a different task name."
        )

    dest_path = task_dir / upload.filename

    size = 0
    try:
        with dest_path.open("wb") as f:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Uploaded file exceeds size limit")
                f.write(chunk)
    except HTTPException:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded script: {exc}")
    finally:
        # Explicitly close the file to release handles (important for Windows file locks)
        upload.file.close()

    if suffix == ".zip":
        try:
            with zipfile.ZipFile(dest_path) as zf:
                _safe_extract(zf, task_dir)
        except zipfile.BadZipFile:
            shutil.rmtree(task_dir, ignore_errors=True)
            raise HTTPException(status_code=422, detail="Uploaded .zip is not a valid archive")
        dest_path.unlink()  # drop the archive, keep only extracted module files
        return str(task_dir)

    # single .tf file
    return str(dest_path)


def _safe_extract(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """Guards against zip-slip path traversal during extraction."""
    for member in zf.namelist():
        member_path = (dest_dir / member).resolve()
        if not str(member_path).startswith(str(dest_dir.resolve())):
            raise HTTPException(status_code=422, detail=f"Unsafe path in archive: {member}")
    zf.extractall(dest_dir)

    # Hoist contents if the zip contains a single top-level directory wrapping everything.
    # Exclude the temporary zip archive itself and metadata folders (like __MACOSX) from checks.
    subdirs = [p for p in dest_dir.iterdir() if p.is_dir() and p.name != "__MACOSX"]
    other_files = [p for p in dest_dir.iterdir() if p.is_file() and p.suffix != ".zip"]
    
    if len(subdirs) == 1 and len(other_files) == 0:
        single_dir = subdirs[0]
        for item in single_dir.iterdir():
            shutil.move(str(item), str(dest_dir))
        single_dir.rmdir()


@router.post("/admin/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_name: str = Form(..., description="Unique alphanumeric identifier for the task"),
    display_name: str = Form(...),
    description: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    provider: Optional[str] = Form(None),
    module_version: Optional[str] = Form(None),
    script: UploadFile = ...,
    db: Session = Depends(get_db),
    redis: Any = Depends(get_arq_pool),
    _admin=Depends(require_admin),
):
    # Validate task_name format
    if not re.match(r"^[a-zA-Z0-9_-]+$", task_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="task_name must contain only alphanumeric characters, underscores, and hyphens."
        )

    # Check for uniqueness in database
    existing_task = db.query(Task).filter(Task.task_name == task_name).first()
    if existing_task:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task with name '{task_name}' already exists."
        )

    module_source = _save_script(task_name, script)
    schema = _generate_schema_from_tf(module_source)

    task = Task(
        task_name=task_name,
        display_name=display_name,
        description=description,
        input_schema=schema,
        module_source=module_source,
        module_version=module_version,
        category=category,
        provider=provider,
    )

    try:
        db.add(task)
        db.commit()
        db.refresh(task)
    except Exception as exc:
        db.rollback()
        shutil.rmtree(settings.TASK_SCRIPTS_ROOT / task_name, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to create task: {exc}")

    # Update Redis distinct count hashes incrementally
    try:
        if task.category:
            await redis.hincrby("categories:distinct", task.category, 1)
        if task.provider:
            await redis.hincrby("providers:distinct", task.provider, 1)
    except Exception as exc:
        print(f"[Warning] Failed to increment Redis distinct count for task '{task_name}': {exc}")

    return task


@router.delete("/admin/tasks/{task_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_name: str,
    db: Session = Depends(get_db),
    redis: Any = Depends(get_arq_pool),
    _admin=Depends(require_admin),
):
    task = db.query(Task).filter(Task.task_name == task_name).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Prevent deleting the task if it has associated deployments.
    # The user must delete the deployments first to trigger Terraform resource teardown.
    deployments_count = db.query(Deployment).filter(Deployment.task_name == task_name).count()
    if deployments_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete task '{task_name}' because it has {deployments_count} associated deployment(s). "
                   f"Please destroy and delete those deployments first to avoid orphaned cloud resources."
        )

    # Clean up the task registry scripts directory on disk
    task_dir = settings.TASK_SCRIPTS_ROOT / task_name
    if task_dir.exists() and task_dir.is_dir():
        shutil.rmtree(task_dir, ignore_errors=True)

    # Store category and provider before deleting row
    task_category = task.category
    task_provider = task.provider

    # Delete task database row
    db.delete(task)
    db.commit()

    # Decrement Redis distinct counts incrementally
    try:
        if task_category:
            new_cat_cnt = await redis.hincrby("categories:distinct", task_category, -1)
            if new_cat_cnt <= 0:
                await redis.hdel("categories:distinct", task_category)
        if task_provider:
            new_prov_cnt = await redis.hincrby("providers:distinct", task_provider, -1)
            if new_prov_cnt <= 0:
                await redis.hdel("providers:distinct", task_provider)
    except Exception as exc:
        print(f"[Warning] Failed to decrement Redis distinct count for task '{task_name}': {exc}")