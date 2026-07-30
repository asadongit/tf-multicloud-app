import os
import httpx
from mcp.server.mcpserver import MCPServer

# Initialize MCPServer
mcp = MCPServer("Terraform-Engine-MCP")

# Target the local running FastAPI application (port 8000 is default for fastapi dev)
API_BASE_URL = os.getenv("TERRAFORM_ENGINE_API_URL", "http://127.0.0.1:8001/api")

# Headers for authentication
# app/mcp_server.py
import os

HEADERS = {
    "X-User-Id": os.getenv("TERRAFORM_ENGINE_USER_ID", "default-user"),
    "X-Admin-Token": os.getenv("TERRAFORM_ENGINE_ADMIN_TOKEN", "default-token")
}


@mcp.tool()
async def list_tasks() -> str:
    """
    List all available Terraform tasks (templates) in the registry.
    Returns:
        JSON string representing the list of tasks and their details.
    """
    #user_token = ctx.request_context.get("authorization_header")
    #headers = {"Authorization": f"Bearer {user_token}"}

    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE_URL}/tasks", headers=HEADERS)
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
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE_URL}/tasks/{task_name}", headers=HEADERS)
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
        async with httpx.AsyncClient() as client:
            params = {"deployment_name": deployment_name}
            response = await client.post(
                f"{API_BASE_URL}/provision/{task_name}",
                params=params,
                json=payload,
                headers=HEADERS
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
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/deployments/name/{deployment_name}",
                headers=HEADERS
            )
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
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{API_BASE_URL}/deployments/name/{deployment_name}",
                headers=HEADERS
            )
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

if __name__ == "__main__":
    mcp.run()
