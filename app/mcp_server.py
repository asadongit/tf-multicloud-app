import json
import os
import httpx
from fastmcp import FastMCP
from contextlib import asynccontextmanager

# Target the local running FastAPI application
API_BASE_URL = os.getenv("TERRAFORM_ENGINE_API_URL", "http://127.0.0.1:8000/api")

# Headers for authentication
HEADERS = {
    "X-User-Id": os.getenv("TERRAFORM_ENGINE_USER_ID", "default-user"),
    "X-Admin-Token": os.getenv("TERRAFORM_ENGINE_ADMIN_TOKEN", "default-token")
}

# Connection Pooling
http_client: httpx.AsyncClient | None = None

async def get_http_client() -> httpx.AsyncClient:
    global http_client
    if http_client is None or http_client.is_closed:
        http_client = httpx.AsyncClient(base_url=API_BASE_URL, headers=HEADERS)
    return http_client

@asynccontextmanager
async def manage_http_lifecycle(server):
    global http_client
    http_client = httpx.AsyncClient(base_url=API_BASE_URL, headers=HEADERS)
    try:
        yield
    finally:
        if http_client and not http_client.is_closed:
            await http_client.aclose()
            http_client = None

# Initialize FastMCP
mcp = FastMCP("Terraform-Engine-MCP", lifespan=manage_http_lifecycle)


# Catalog Context MCP Resources
@mcp.resource("catalog://categories")
async def get_categories_resource() -> str:
    """Exposes all registered infrastructure categories as a native MCP Resource."""
    try:
        client = await get_http_client()
        response = await client.get("/categories/distinct")
        response.raise_for_status()
        return response.text
    except Exception:
        return json.dumps(["compute", "database", "storage", "network", "security", "serverless", "messaging"])

@mcp.resource("catalog://providers")
async def get_providers_resource() -> str:
    """Exposes all registered cloud providers as a native MCP Resource."""
    try:
        client = await get_http_client()
        response = await client.get("/providers/distinct")
        response.raise_for_status()
        return response.text
    except Exception:
        return json.dumps(["aws", "azure", "gcp", "kubernetes", "local"])


@mcp.tool()
async def list_tasks(category: str = None, provider: str = None) -> str:
    """
    List available Terraform tasks (templates) in the registry.
    Args:
        category: Optional category filter (e.g. compute, database, storage, network, security, serverless, messaging).
        provider: Optional cloud provider filter (e.g. aws, azure, gcp, kubernetes, local).
    Returns:
        JSON string representing the list of tasks and their details.
    """
    params = {"view": "summary"}
    if category:
        params["category"] = category
    if provider:
        params["provider"] = provider
        
    try:
        client = await get_http_client()
        response = await client.get("/tasks", params=params)
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as exc:
        return f"HTTP error occurred while listing tasks: {exc}"
    except Exception as exc:
        return f"Unexpected error: {exc}"


@mcp.tool()
async def get_task_schema(task_name: str) -> str:
    """
    Get the metadata and input schema (JSON Schema) for a registered task.
    Args:
        task_name: The unique alphanumeric name of the task.
    """
    try:
        client = await get_http_client()
        response = await client.get(f"/tasks/{task_name}")
        if response.status_code == 404:
            return f"Error: Task '{task_name}' not found."
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as exc:
        return f"HTTP error occurred while getting task schema: {exc}"
    except Exception as exc:
        return f"Unexpected error: {exc}"


@mcp.tool()
async def provision_task(task_name: str, deployment_name: str, payload: dict) -> str:
    """
    Provision a new deployment for a given task.
    Args:
        task_name: The registered task name to deploy.
        deployment_name: A unique name for this deployment instance.
        payload: JSON object/dictionary containing the variables matching the task schema.
    """
    try:
        params = {"deployment_name": deployment_name}
        client = await get_http_client()
        response = await client.post(
            f"/provision/{task_name}",
            params=params,
            json=payload
        )
        if response.status_code == 422:
            detail = response.json().get('detail')
            return f"Validation Error: {detail}"
        if response.status_code == 404:
            return f"Error: Task '{task_name}' not found."
        if response.status_code == 400:
            detail = response.json().get('detail')
            return f"Error: {detail}"
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as exc:
        return f"HTTP error occurred while provisioning task: {exc}"
    except Exception as exc:
        return f"Unexpected error: {exc}"


@mcp.tool()
async def get_deployment_status(deployment_name: str) -> str:
    """
    Get the current status, configurations, and outputs of a deployment by its name.
    Args:
        deployment_name: The unique name of the deployment to inspect.
    """
    try:
        client = await get_http_client()
        response = await client.get(f"/deployments/name/{deployment_name}")
        if response.status_code == 404:
            return f"Error: Deployment '{deployment_name}' not found."
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as exc:
        return f"HTTP error occurred while getting deployment status: {exc}"
    except Exception as exc:
        return f"Unexpected error: {exc}"


@mcp.tool()
async def destroy_deployment(deployment_name: str) -> str:
    """
    Tear down and delete an existing deployment by its name.
    Args:
        deployment_name: The name of the deployment to destroy.
    """
    try:
        client = await get_http_client()
        response = await client.delete(f"/deployments/name/{deployment_name}")
        if response.status_code == 404:
            return f"Error: Deployment '{deployment_name}' not found."
        if response.status_code == 400:
            detail = response.json().get('detail')
            return f"Error: {detail}"
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as exc:
        return f"HTTP error occurred while destroying deployment: {exc}"
    except Exception as exc:
        return f"Unexpected error: {exc}"


@mcp.tool()
async def list_deployments(status: str = None) -> str:
    """
    List all active or past deployments in the registry.
    Args:
        status: Optional status filter to filter deployments (e.g. ACTIVE, FAILED, PENDING, DESTROYED).
    Returns:
        JSON string representing the list of deployments and their summary details.
    """
    params = {"view": "summary"}
    if status:
        params["status"] = status
        
    try:
        client = await get_http_client()
        response = await client.get("/deployments", params=params)
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as exc:
        return f"HTTP error occurred while listing deployments: {exc}"
    except Exception as exc:
        return f"Unexpected error: {exc}"


if __name__ == "__main__":
    mcp.run()
