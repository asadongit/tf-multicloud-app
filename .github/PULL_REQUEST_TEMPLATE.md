## Description

Please include a summary of the change and which issue is fixed. Include relevant motivation, context, and any design decisions made.

Fixes # (issue)

## Type of change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] LLM Guardrail / System Prompt update
- [ ] API endpoint change (new route, modified schema, or status code change)
- [ ] Documentation update
- [ ] Code reorganization / refactoring

## Components Affected

- [ ] API Endpoints (`app/api/`)
- [ ] LLM Orchestrator (`app/core/llm_orchestrator.py`)
- [ ] History Manager (`app/core/history_manager.py`)
- [ ] MCP Server (`app/mcp_server.py`)
- [ ] Background Worker (`app/worker.py`)
- [ ] Database Models (`app/models/`)
- [ ] Frontend / Templates (`app/templates/`)
- [ ] CI / GitHub Actions (`.github/workflows/`)
- [ ] Documentation (`docs/`, `README.md`)

## How Has This Been Tested?

Describe the tests you ran to verify your changes. Provide instructions so we can reproduce.

- [ ] Unit Tests: `uv run pytest`
- [ ] AI Chat manual testing (verified tool-calling flow)
- [ ] Manual verification via Swagger UI at `/docs`
- [ ] Manual verification via Dashboard UI

**Test Configuration**:
* OS:
* Python version:
* LLM Provider / Model (if applicable):
* Redis running: Yes / No (MockArqRedis fallback)

## Checklist

- [ ] My code follows the style guidelines of this project
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation (`README.md`, `docs/architecture.md`)
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] If I modified system prompt guardrails, I have tested against small/free LLMs (e.g., Groq Llama-3.3)
- [ ] If I modified API schemas, I have verified backward compatibility or documented breaking changes
