from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.runtime import get_execution_mode, set_execution_mode


router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class ExecutionModeRequest(BaseModel):
    mode: str


@router.get("/execution-mode")
async def get_mcp_execution_mode():
    settings = get_settings()
    return {
        "mode": get_execution_mode(),
        "allowlist": settings.mcp_command_allowlist,
    }


@router.post("/execution-mode")
async def update_mcp_execution_mode(payload: ExecutionModeRequest):
    try:
        set_execution_mode(payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"mode": get_execution_mode()}
