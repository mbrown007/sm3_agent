from __future__ import annotations

from backend.app.config import get_settings


_EXECUTION_MODE = get_settings().mcp_execution_mode


def get_execution_mode() -> str:
    return _EXECUTION_MODE


def set_execution_mode(mode: str) -> None:
    normalized = mode.strip().lower()
    if normalized not in {"suggest", "execute"}:
        raise ValueError("Execution mode must be 'suggest' or 'execute'")
    global _EXECUTION_MODE
    _EXECUTION_MODE = normalized
