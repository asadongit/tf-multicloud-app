import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from sqlalchemy.orm import Session
from arq.connections import RedisSettings
from sqlalchemy import func
from arq.cron import cron

from app.core.database import SessionLocal
from app.models.task import Task
from app.models.deployment import Deployment, DeploymentStatus
from app.core.config import settings


def load_global_modules(run_dir: Path):
    """Copies all cached modules and the merged modules.json from the global cache
    to the run directory's .terraform/modules directory.
    """
    global_modules_dir = settings.GLOBAL_MODULES_CACHE / "modules"
    if not global_modules_dir.exists():
        return
        
    run_modules_dir = run_dir / ".terraform" / "modules"
    run_modules_dir.mkdir(parents=True, exist_ok=True)
    
    shutil.copytree(global_modules_dir, run_modules_dir, dirs_exist_ok=True)


def merge_global_modules(run_dir: Path):
    """Copies newly downloaded modules and merges modules.json from the run directory
    back to the global modules cache.
    """
    run_modules_dir = run_dir / ".terraform" / "modules"
    if not run_modules_dir.exists():
        return
        
    global_modules_dir = settings.GLOBAL_MODULES_CACHE / "modules"
    global_modules_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Copy module directories from run_dir to global cache (excluding modules.json)
    for item in run_modules_dir.iterdir():
        if item.is_dir() and item.name != "modules.json":
            shutil.copytree(item, global_modules_dir / item.name, dirs_exist_ok=True)
            
    # 2. Merge modules.json contents
    run_json_path = run_modules_dir / "modules.json"
    global_json_path = global_modules_dir / "modules.json"
    
    if not run_json_path.exists():
        return
        
    try:
        with run_json_path.open("r", encoding="utf-8") as f:
            run_data = json.load(f)
    except Exception:
        return
        
    global_data = {"Modules": []}
    if global_json_path.exists():
        try:
            with global_json_path.open("r", encoding="utf-8") as f:
                global_data = json.load(f)
        except Exception:
            pass
            
    run_modules = run_data.get("Modules", [])
    global_modules = global_data.get("Modules", [])
    
    # Track uniqueness using (Source, Dir, Key)
    existing = set()
    merged = []
    
    for m in global_modules:
        key = (m.get("Source"), m.get("Dir"), m.get("Key"))
        if key not in existing:
            existing.add(key)
            merged.append(m)
            
    for m in run_modules:
        key = (m.get("Source"), m.get("Dir"), m.get("Key"))
        if key not in existing:
            existing.add(key)
            merged.append(m)
            
    global_data["Modules"] = merged
    
    try:
        with global_json_path.open("w", encoding="utf-8") as f:
            json.dump(global_data, f, indent=2)
    except Exception:
        pass


def run_command_with_streaming(cmd: list[str], cwd: Path, env: dict = None) -> subprocess.CompletedProcess:
    """Runs a command, streaming its stdout and stderr in real-time to the console,
    while also capturing them to be returned.
    """
    if os.environ.get("TESTING") == "true":
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env
        )

    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )
    
    stdout_accum = []
    stderr_accum = []
    
    def read_stdout():
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            stdout_accum.append(line)
            
    def read_stderr():
        for line in process.stderr:
            sys.stderr.write(line)
            sys.stderr.flush()
            stderr_accum.append(line)
            
    t1 = threading.Thread(target=read_stdout)
    t2 = threading.Thread(target=read_stderr)
    
    t1.start()
    t2.start()
    
    process.wait()
    t1.join()
    t2.join()
    
    stdout_str = "".join(stdout_accum)
    stderr_str = "".join(stderr_accum)
    
    return subprocess.CompletedProcess(
        args=cmd,
        returncode=process.returncode,
        stdout=stdout_str,
        stderr=stderr_str
    )


async def run_terraform_create(ctx, run_id: str, deployment_id: str, task_name: str, module_source: str, inputs: dict):
    print(f"[{run_id}] Starting terraform create for deployment {deployment_id} (task: {task_name})")
    
    db: Session = SessionLocal()
    try:
        # 1. Update status to PROVISIONING in worker just in case
        deployment = db.query(Deployment).filter(Deployment.deployment_id == deployment_id).first()
        if not deployment:
            print(f"[{run_id}] Error: Deployment {deployment_id} not found in DB.")
            return
        
        deployment.status = DeploymentStatus.PROVISIONING
        db.commit()
 
        # 2. Set up isolated run directory
        run_dir = settings.DEPLOYMENTS_ROOT / deployment_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Copy module files
        source_path = Path(module_source)
        if source_path.is_dir():
            shutil.copytree(source_path, run_dir, dirs_exist_ok=True)
        elif source_path.is_file():
            shutil.copy(source_path, run_dir / source_path.name)
        else:
            raise RuntimeError(f"module_source '{module_source}' does not exist on disk")

        # Write inputs as terraform.tfvars.json
        tfvars_path = run_dir / "terraform.tfvars.json"
        with tfvars_path.open("w") as f:
            json.dump(inputs, f, indent=2)

        # Prepare environment with TF_PLUGIN_CACHE_DIR to cache provider binaries
        env = os.environ.copy()
        env["TF_PLUGIN_CACHE_DIR"] = str(settings.TERRAFORM_PLUGIN_CACHE)

        # Load cache: check task_dir, then legacy task_cache_dir, then global modules cache
        task_dir = source_path if source_path.is_dir() else source_path.parent
        task_tf_dir = task_dir / ".terraform"
        task_lock_file = task_dir / ".terraform.lock.hcl"
        legacy_cache_dir = settings.GLOBAL_MODULES_CACHE.parent / task_name
        legacy_cache_dir.mkdir(parents=True, exist_ok=True)

        has_task_cache = False
        if task_tf_dir.exists():
            shutil.copytree(task_tf_dir, run_dir / ".terraform", dirs_exist_ok=True)
            has_task_cache = True
        elif legacy_cache_dir.exists():
            legacy_tf_dir = legacy_cache_dir / ".terraform"
            if legacy_tf_dir.exists():
                shutil.copytree(legacy_tf_dir, run_dir / ".terraform", dirs_exist_ok=True)
                has_task_cache = True

        if task_lock_file.exists():
            shutil.copy(task_lock_file, run_dir / ".terraform.lock.hcl")
        elif legacy_cache_dir.exists():
            legacy_lock = legacy_cache_dir / ".terraform.lock.hcl"
            if legacy_lock.exists() and not (run_dir / ".terraform.lock.hcl").exists():
                shutil.copy(legacy_lock, run_dir / ".terraform.lock.hcl")

        if not has_task_cache:
            load_global_modules(run_dir)

        # 3. Run terraform init
        try:
            init_res = run_command_with_streaming(
                ["terraform", "init", "-input=false", "-no-color"],
                cwd=run_dir,
                env=env
            )
        except FileNotFoundError:
            raise RuntimeError("Terraform CLI not found on system. Please install Terraform.")

        if init_res.returncode != 0:
            raise RuntimeError(f"terraform init failed: {init_res.stderr or init_res.stdout}")

        # Save cache back to task directory, legacy cache directory, and merge to global module cache
        run_tf_dir = run_dir / ".terraform"
        run_lock = run_dir / ".terraform.lock.hcl"

        if run_tf_dir.exists():
            shutil.copytree(run_tf_dir, task_dir / ".terraform", ignore=shutil.ignore_patterns("providers"), dirs_exist_ok=True)
            shutil.copytree(run_tf_dir, legacy_cache_dir / ".terraform", ignore=shutil.ignore_patterns("providers"), dirs_exist_ok=True)
            merge_global_modules(run_dir)

        if run_lock.exists():
            shutil.copy(run_lock, task_dir / ".terraform.lock.hcl")
            shutil.copy(run_lock, legacy_cache_dir / ".terraform.lock.hcl")

        # 4. Run terraform apply
        apply_res = run_command_with_streaming(
            ["terraform", "apply", "-auto-approve", "-input=false", "-no-color"],
            cwd=run_dir,
            env=env
        )
        if apply_res.returncode != 0:
            raise RuntimeError(f"terraform apply failed: {apply_res.stderr or apply_res.stdout}")

        # 5. Fetch terraform outputs
        output_res = subprocess.run(
            ["terraform", "output", "-json"],
            cwd=run_dir,
            capture_output=True,
            text=True
        )
        outputs = {}
        if output_res.returncode == 0 and output_res.stdout.strip():
            tf_outputs = json.loads(output_res.stdout)
            outputs = {k: v.get("value") for k, v in tf_outputs.items()}

        # 6. Update deployment row to ACTIVE
        deployment.status = DeploymentStatus.ACTIVE
        deployment.outputs = outputs
        deployment.state_path = str((run_dir / "terraform.tfstate").resolve())
        db.commit()
        print(f"[{run_id}] Successfully provisioned deployment {deployment_id}")

    except Exception as exc:
        db.rollback()
        # Reload deployment reference to update with failure details
        deployment = db.query(Deployment).filter(Deployment.deployment_id == deployment_id).first()
        if deployment:
            deployment.status = DeploymentStatus.FAILED
            deployment.last_error = str(exc)
            db.commit()
        print(f"[{run_id}] Failed to provision deployment {deployment_id}: {exc}")
    finally:
        db.close()


async def run_terraform_destroy(ctx, run_id: str, deployment_id: str):
    print(f"[{run_id}] Starting terraform destroy for deployment {deployment_id}")
    
    db: Session = SessionLocal()
    try:
        # 1. Ensure status is DESTROYING in DB
        deployment = db.query(Deployment).filter(Deployment.deployment_id == deployment_id).first()
        if not deployment:
            print(f"[{run_id}] Error: Deployment {deployment_id} not found in DB.")
            return
        
        deployment.status = DeploymentStatus.DESTROYING
        db.commit()

        # 2. Get isolated run directory
        run_dir = settings.DEPLOYMENTS_ROOT / deployment_id
        
        # Check if there are any .tf files in the run directory
        has_tf_files = False
        if run_dir.exists() and run_dir.is_dir():
            has_tf_files = any(run_dir.glob("*.tf"))

        if not run_dir.exists() or not run_dir.is_dir() or not has_tf_files:
            # If the directory doesn't exist or has no configuration (.tf) files,
            # we cannot run destroy. Clean up and remove from DB directly.
            shutil.rmtree(run_dir, ignore_errors=True)
            db.delete(deployment)
            db.commit()
            print(f"[{run_id}] Run directory '{run_dir}' is missing or has no .tf files. Removed deployment from DB directly.")
            return

        # Prepare environment with TF_PLUGIN_CACHE_DIR to cache provider binaries
        env = os.environ.copy()
        env["TF_PLUGIN_CACHE_DIR"] = str(settings.TERRAFORM_PLUGIN_CACHE)

        # Get module_source from Task DB row to resolve its path
        task = db.query(Task).filter(Task.task_name == deployment.task_name).first()
        if not task:
            raise RuntimeError(f"Task '{deployment.task_name}' not found in catalog")

        source_path = Path(task.module_source)
        task_dir = source_path if source_path.is_dir() else source_path.parent
        task_tf_dir = task_dir / ".terraform"
        task_lock_file = task_dir / ".terraform.lock.hcl"
        legacy_cache_dir = settings.GLOBAL_MODULES_CACHE.parent / deployment.task_name
        legacy_cache_dir.mkdir(parents=True, exist_ok=True)

        # Load cache: check task_dir, then legacy task_cache_dir, then global modules cache
        has_task_cache = False
        if task_tf_dir.exists():
            shutil.copytree(task_tf_dir, run_dir / ".terraform", dirs_exist_ok=True)
            has_task_cache = True
        elif legacy_cache_dir.exists():
            legacy_tf_dir = legacy_cache_dir / ".terraform"
            if legacy_tf_dir.exists():
                shutil.copytree(legacy_tf_dir, run_dir / ".terraform", dirs_exist_ok=True)
                has_task_cache = True

        if task_lock_file.exists():
            shutil.copy(task_lock_file, run_dir / ".terraform.lock.hcl")
        elif legacy_cache_dir.exists():
            legacy_lock = legacy_cache_dir / ".terraform.lock.hcl"
            if legacy_lock.exists() and not (run_dir / ".terraform.lock.hcl").exists():
                shutil.copy(legacy_lock, run_dir / ".terraform.lock.hcl")

        if not has_task_cache:
            load_global_modules(run_dir)

        # 3. Run terraform init
        try:
            init_res = run_command_with_streaming(
                ["terraform", "init", "-input=false", "-no-color"],
                cwd=run_dir,
                env=env
            )
        except FileNotFoundError:
            raise RuntimeError("Terraform CLI not found on system. Please install Terraform.")

        if init_res.returncode != 0:
            raise RuntimeError(f"terraform init failed: {init_res.stderr or init_res.stdout}")

        # Save cache back to task directory, legacy cache directory, and merge to global module cache
        run_tf_dir = run_dir / ".terraform"
        run_lock = run_dir / ".terraform.lock.hcl"

        if run_tf_dir.exists():
            shutil.copytree(run_tf_dir, task_dir / ".terraform", ignore=shutil.ignore_patterns("providers"), dirs_exist_ok=True)
            shutil.copytree(run_tf_dir, legacy_cache_dir / ".terraform", ignore=shutil.ignore_patterns("providers"), dirs_exist_ok=True)
            merge_global_modules(run_dir)

        if run_lock.exists():
            shutil.copy(run_lock, task_dir / ".terraform.lock.hcl")
            shutil.copy(run_lock, legacy_cache_dir / ".terraform.lock.hcl")

        # 4. Run terraform destroy
        destroy_res = run_command_with_streaming(
            ["terraform", "destroy", "-auto-approve", "-input=false", "-no-color"],
            cwd=run_dir,
            env=env
        )

        if destroy_res.returncode != 0:
            raise RuntimeError(f"terraform destroy failed: {destroy_res.stderr or destroy_res.stdout}")

        # 4. Clean up isolated run directory
        shutil.rmtree(run_dir, ignore_errors=True)

        # 5. Delete deployment row from DB
        db.delete(deployment)
        db.commit()
        print(f"[{run_id}] Successfully destroyed and deleted deployment {deployment_id}")

    except Exception as exc:
        db.rollback()
        # Reload deployment reference to update with failure details
        deployment = db.query(Deployment).filter(Deployment.deployment_id == deployment_id).first()
        if deployment:
            deployment.status = DeploymentStatus.FAILED
            deployment.last_error = f"Terraform destroy failed: {exc}"
            db.commit()
        print(f"[{run_id}] Failed to destroy deployment {deployment_id}: {exc}")
    finally:
        db.close()


async def run_terraform_update(ctx, run_id: str, deployment_id: str, inputs: dict):
    print(f"[{run_id}] Starting terraform update for deployment {deployment_id}")
    
    db: Session = SessionLocal()
    try:
        deployment = db.query(Deployment).filter(Deployment.deployment_id == deployment_id).first()
        if not deployment:
            print(f"[{run_id}] Error: Deployment {deployment_id} not found in DB.")
            return

        deployment.status = DeploymentStatus.UPDATING
        db.commit()

        run_dir = settings.DEPLOYMENTS_ROOT / deployment_id
        if not run_dir.exists() or not run_dir.is_dir():
            raise RuntimeError(f"Run directory '{run_dir}' not found. Cannot update deployment.")

        # Write inputs as terraform.tfvars.json
        tfvars_path = run_dir / "terraform.tfvars.json"
        with tfvars_path.open("w") as f:
            json.dump(inputs, f, indent=2)

        # Prepare environment with TF_PLUGIN_CACHE_DIR to cache provider binaries
        env = os.environ.copy()
        env["TF_PLUGIN_CACHE_DIR"] = str(settings.TERRAFORM_PLUGIN_CACHE)

        # Ensure .terraform directory exists or retrieve it from cache
        task = db.query(Task).filter(Task.task_name == deployment.task_name).first()
        if not task:
            raise RuntimeError(f"Task '{deployment.task_name}' not found in catalog")

        source_path = Path(task.module_source)
        task_dir = source_path if source_path.is_dir() else source_path.parent
        task_tf_dir = task_dir / ".terraform"
        task_lock_file = task_dir / ".terraform.lock.hcl"
        legacy_cache_dir = settings.GLOBAL_MODULES_CACHE.parent / deployment.task_name
        legacy_cache_dir.mkdir(parents=True, exist_ok=True)

        # Restore cache if .terraform directory doesn't exist in run_dir
        if not (run_dir / ".terraform").exists():
            has_task_cache = False
            if task_tf_dir.exists():
                shutil.copytree(task_tf_dir, run_dir / ".terraform", dirs_exist_ok=True)
                has_task_cache = True
            elif legacy_cache_dir.exists():
                legacy_tf_dir = legacy_cache_dir / ".terraform"
                if legacy_tf_dir.exists():
                    shutil.copytree(legacy_tf_dir, run_dir / ".terraform", dirs_exist_ok=True)
                    has_task_cache = True

            if task_lock_file.exists():
                shutil.copy(task_lock_file, run_dir / ".terraform.lock.hcl")
            elif legacy_cache_dir.exists():
                legacy_lock = legacy_cache_dir / ".terraform.lock.hcl"
                if legacy_lock.exists() and not (run_dir / ".terraform.lock.hcl").exists():
                    shutil.copy(legacy_lock, run_dir / ".terraform.lock.hcl")

            if not has_task_cache:
                load_global_modules(run_dir)

        # 3. Run terraform init
        try:
            init_res = run_command_with_streaming(
                ["terraform", "init", "-input=false", "-no-color"],
                cwd=run_dir,
                env=env
            )
        except FileNotFoundError:
            raise RuntimeError("Terraform CLI not found on system. Please install Terraform.")

        if init_res.returncode != 0:
            raise RuntimeError(f"terraform init failed: {init_res.stderr or init_res.stdout}")

        # Save cache back
        run_tf_dir = run_dir / ".terraform"
        run_lock = run_dir / ".terraform.lock.hcl"

        if run_tf_dir.exists():
            shutil.copytree(run_tf_dir, task_dir / ".terraform", ignore=shutil.ignore_patterns("providers"), dirs_exist_ok=True)
            shutil.copytree(run_tf_dir, legacy_cache_dir / ".terraform", ignore=shutil.ignore_patterns("providers"), dirs_exist_ok=True)
            merge_global_modules(run_dir)

        if run_lock.exists():
            shutil.copy(run_lock, task_dir / ".terraform.lock.hcl")
            shutil.copy(run_lock, legacy_cache_dir / ".terraform.lock.hcl")

        # 4. Run terraform apply
        apply_res = run_command_with_streaming(
            ["terraform", "apply", "-auto-approve", "-input=false", "-no-color"],
            cwd=run_dir,
            env=env
        )
        if apply_res.returncode != 0:
            raise RuntimeError(f"terraform apply failed: {apply_res.stderr or apply_res.stdout}")

        # 5. Fetch terraform outputs
        output_res = subprocess.run(
            ["terraform", "output", "-json"],
            cwd=run_dir,
            capture_output=True,
            text=True
        )
        outputs = {}
        if output_res.returncode == 0 and output_res.stdout.strip():
            tf_outputs = json.loads(output_res.stdout)
            outputs = {k: v.get("value") for k, v in tf_outputs.items()}

        # 6. Update deployment row to ACTIVE
        deployment.status = DeploymentStatus.ACTIVE
        deployment.outputs = outputs
        db.commit()
        print(f"[{run_id}] Successfully updated deployment {deployment_id}")

    except Exception as exc:
        db.rollback()
        # Reload deployment reference to update with failure details
        deployment = db.query(Deployment).filter(Deployment.deployment_id == deployment_id).first()
        if deployment:
            deployment.status = DeploymentStatus.FAILED
            deployment.last_error = str(exc)
            db.commit()
        print(f"[{run_id}] Failed to update deployment {deployment_id}: {exc}")
    finally:
        db.close()




async def reconcile_distinct_counts(ctx):
    """Periodic Arq reconciliation job that recomputes ground truth counts from SQL and overwrites Redis Hashes."""
    print("[Arq] Running reconcile_distinct_counts background job...")
    db = SessionLocal()
    try:
        redis = ctx.get("redis") if ctx and isinstance(ctx, dict) else None
        if not redis:
            from app.core.queue import get_arq_pool
            redis = await get_arq_pool()
        
        # 1. Categories
        cat_rows = db.query(Task.category, func.count(Task.task_name))\
            .filter(Task.category.isnot(None))\
            .group_by(Task.category).all()
        cat_counts = {val: count for val, count in cat_rows if val}
        if cat_counts:
            await redis.hset("categories:distinct", mapping=cat_counts)
            
        # 2. Providers
        prov_rows = db.query(Task.provider, func.count(Task.task_name))\
            .filter(Task.provider.isnot(None))\
            .group_by(Task.provider).all()
        prov_counts = {val: count for val, count in prov_rows if val}
        if prov_counts:
            await redis.hset("providers:distinct", mapping=prov_counts)
            
        print(f"[Arq] Reconciled distinct counts: {len(cat_counts)} categories, {len(prov_counts)} providers.")
    except Exception as exc:
        print(f"[Arq Error] Failed to reconcile distinct counts: {exc}")
    finally:
        db.close()


class WorkerSettings:
    functions = [run_terraform_create, run_terraform_destroy, run_terraform_update, reconcile_distinct_counts]
    cron_jobs = [cron(reconcile_distinct_counts, hour=0, minute=0)]
    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT
    )
