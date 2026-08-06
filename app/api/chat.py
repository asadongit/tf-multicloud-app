from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from app.agent.orchestrator import handle_turn
from app.core.llm_orchestrator import execute_chat_loop

router = APIRouter(prefix="/api", tags=["chat"])

class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    custom_url: Optional[str] = None
    session_id: Optional[str] = "default"

@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id")
):
    """
    Executes a turn of the deterministic FSM assistant orchestrator.
    """
    try:
        effective_session_id = x_session_id or request.session_id or "default"
        raw_messages = [m.model_dump(exclude_none=True) for m in request.messages]
        result = await handle_turn(
            messages=raw_messages,
            session_id=effective_session_id,
            provider=request.provider,
            model=request.model,
            api_key=request.api_key,
            custom_url=request.custom_url
        )
        return result
    except ValueError as ve:
        raise HTTPException(status_code=401, detail=str(ve))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/chat/legacy")
async def chat_legacy_endpoint(
    request: ChatRequest
):
    """
    Executes a turn of the legacy ReAct LLM orchestrator loop.
    """
    try:
        raw_messages = [m.model_dump(exclude_none=True) for m in request.messages]
        result = await execute_chat_loop(
            messages=raw_messages,
            provider=request.provider,
            model=request.model,
            api_key=request.api_key,
            custom_url=request.custom_url
        )
        return result
    except ValueError as ve:
        raise HTTPException(status_code=401, detail=str(ve))
    except RuntimeError as re:
        err_msg = str(re)
        if "401" in err_msg or "API Key" in err_msg:
            raise HTTPException(status_code=401, detail=err_msg)
        if "HTTP Connection Error" in err_msg or "connect" in err_msg.lower():
            raise HTTPException(status_code=502, detail=err_msg)
        raise HTTPException(status_code=500, detail=err_msg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"HTTP Connection Error: {exc}")



