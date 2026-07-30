import os
from pathlib import Path

class Settings:
    TESTING: bool = os.getenv("TESTING", "false").lower() == "true"
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./tasks.db")
    
    # Task Script directories
    TASK_SCRIPTS_ROOT: Path = Path(os.getenv("TASK_SCRIPTS_ROOT", "./task_scripts"))
    DEPLOYMENTS_ROOT: Path = Path(os.getenv("DEPLOYMENTS_ROOT", "./deployments_runs"))
    
    # Cache directories
    TERRAFORM_PLUGIN_CACHE: Path = Path(os.getenv("TERRAFORM_PLUGIN_CACHE", "./.terraform_plugin_cache")).resolve()
    GLOBAL_MODULES_CACHE: Path = Path(os.getenv("GLOBAL_MODULES_CACHE", "./.terraform_cache/global_modules")).resolve()
    
    # Redis config
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))

settings = Settings()

# Ensure directories exist
settings.TASK_SCRIPTS_ROOT.mkdir(parents=True, exist_ok=True)
settings.DEPLOYMENTS_ROOT.mkdir(parents=True, exist_ok=True)
settings.TERRAFORM_PLUGIN_CACHE.mkdir(parents=True, exist_ok=True)
settings.GLOBAL_MODULES_CACHE.mkdir(parents=True, exist_ok=True)
