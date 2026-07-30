# Terraform Engine 🚀

A premium, lightweight, production-ready, self-hosted infrastructure orchestrator. The engine provides administrative controls to register Terraform templates (called Tasks) and exposes a REST API along with a modern, glassmorphic dashboard to provision, update, and teardown environments (called Deployments) asynchronously.

---

## Features

- **FastAPI Core**: Ultra-fast endpoints for registering tasks and managing deployments.
- **Async Execution**: Arq worker backing (with process-level Mock fallback if Redis is missing).
- **Two-Tier Caching**: Near-instantaneous `terraform init` runs with global provider and module caching.
- **Glassmorphism UI**: Beautiful, fully responsive theme-aware dashboard (Light & Dark mode).
- **Comprehensive API**: Supports PATCH updates and clean DELETE teardowns.
- **MCP Server Support**: Exposes local (STDIO) and remote/network (SSE) tools for AI agents (ChatGPT, Claude, Cursor) to manage the infrastructure.
- **Zero-clutter Workspace**: Standard directory package hierarchy ready for GitHub and cloud hosting.

---

## Directory Layout

```
.github/
  workflows/
    ci.yml                  # Automated GitHub Actions testing flow
  PULL_REQUEST_TEMPLATE.md  # Standard pull request format
  ISSUE_TEMPLATE/           # Structured bug and feature templates
app/                        # Main application package
  core/                     # Configurations, Auth, Database, Queue setups
  models/                   # SQLAlchemy database tables
  schemas/                  # Pydantic validation schemas
  api/                      # API endpoint routers (Admin, Public, Lifecycle)
  frontend/                 # Jinja2 HTML page router
  static/                   # Static CSS assets
  templates/                # Layouts and dashboard panels
docs/                       # Detailed architectural design documents
tests/                      # Re-organized pytest test suites
pyproject.toml              # UV-based Python build description
README.md                   # Project runbook
```

See [docs/architecture.md](file:///x:/Onedrive/Desktop/New%20folder/docs/architecture.md) for a detailed deep-dive into the architecture, caching schemes, and lifecycle state workflows.

---

## Getting Started

### Prerequisites

- **Python**: `3.12` or higher.
- **Terraform CLI**: Locally installed and configured.
- **Redis Server** (Optional): Used by `arq` for background queues. Falls back to in-process mock if absent.

### Setup and Installation

This project is configured using [uv](https://github.com/astral-sh/uv) for fast, reliable package management.

1. **Install dependencies and create virtual environment**:
   ```bash
   uv sync
   ```

2. **Activate virtual environment**:
   - On Windows:
     ```powershell
     .venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```bash
     source .venv/bin/activate
     ```

---

## Running the Application

### 1. Run the Web Server
Launch the FastAPI development server:
```bash
uv run uvicorn app.main:app --port 8080 --reload
```
Access the application:
- **Interactive UI Dashboard**: [http://127.0.0.1:8080/](http://127.0.0.1:8080/)
- **Swagger API Docs**: [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs)

### 2. Run the Background Worker
In a separate terminal, launch the `arq` worker:
```bash
uv run arq app.worker.WorkerSettings
```
*(If Redis is not running, the web server falls back to running tasks in-process asynchronously using `MockArqRedis`, so you do not strictly need to start a separate worker for local testing).*

---

## Model Context Protocol (MCP) Setup

This project exposes its tasks and deployments as tools through an MCP server. This allows AI clients (like ChatGPT Desktop, Claude Desktop, or Cursor) to inspect schemas and deploy infrastructure directly.

### 1. Running Locally (STDIO Mode)
Configure your local AI client to launch the MCP server as a subprocess:
* **Command:** `uv`
* **Arguments:** `run --project "/path/to/project" python "/path/to/project/app/mcp_server.py"`

*(Note: Ensure the FastAPI web server is also running locally so the MCP server can forward requests to the API endpoints).*

### 2. Running over the Network (SSE Mode)
When you start the FastAPI web server, the MCP server is automatically mounted and exposed via Server-Sent Events (SSE) at:
```text
http://<YOUR_IP_ADDRESS>:8001/mcp/sse
```
Other devices on the same network can connect to this endpoint directly without needing to launch a local Python command.

---

## Running Tests

To run the automated pytest suite (which covers task creation, validation, provisioning, update patches, and teardown lifecycles):

```bash
uv run pytest
```
All tests execute against an isolated test database `test_tasks.db` and clean up dynamic execution files automatically.
