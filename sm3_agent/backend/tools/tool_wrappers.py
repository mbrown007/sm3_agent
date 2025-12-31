from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Type

import httpx

from langchain.agents import Tool
from langchain.tools import StructuredTool
from pydantic import create_model

from backend.app.config import Settings
from backend.tools.mcp_client import MCPClient
from backend.tools.result_formatter import ToolResultFormatter
from backend.utils.logger import get_logger


logger = get_logger(__name__)
formatter = ToolResultFormatter()

_RELATIVE_TIME_RE = re.compile(r"^now(?:-(\d+)([smhd]))?$")


def _resolve_relative_time(value: str) -> str | None:
    """Convert relative time (now-1h) to RFC3339 UTC timestamp."""
    match = _RELATIVE_TIME_RE.match(value.strip().lower())
    if not match:
        return None

    amount_str, unit = match.groups()
    now = datetime.now(timezone.utc)

    if amount_str and unit:
        amount = int(amount_str)
        delta_map = {
            "s": timedelta(seconds=amount),
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
        }
        now = now - delta_map[unit]

    return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_query_arguments(
    tool_name: str,
    arguments: Dict[str, Any],
    force_step_seconds: bool = False
) -> Dict[str, Any]:
    """Apply defaults for query tools to avoid common MCP errors."""
    if tool_name not in {"query_prometheus", "query_loki_logs"}:
        return arguments

    updated = dict(arguments)

    if tool_name == "query_prometheus":
        query_type = str(updated.get("queryType", "")).lower()
        if force_step_seconds or query_type == "range" or "startTime" in updated or "endTime" in updated:
            updated.setdefault("stepSeconds", 60)

        for key in ("startTime", "endTime"):
            raw = updated.get(key)
            if isinstance(raw, str):
                resolved = _resolve_relative_time(raw)
                if resolved:
                    updated[key] = resolved

    if tool_name == "query_loki_logs":
        for key in ("startRfc3339", "endRfc3339"):
            raw = updated.get(key)
            if isinstance(raw, str):
                resolved = _resolve_relative_time(raw)
                if resolved:
                    updated[key] = resolved

    return updated


def _should_retry_query_error(error: Exception) -> bool:
    message = str(error).lower()
    return (
        "stepseconds must be provided" in message
        or "parsing start time" in message
        or "cannot parse \"now" in message
    )


def _build_args_schema(mcp_tool: Any) -> Optional[Type]:
    """Build a Pydantic args schema from an MCP tool JSON schema."""
    schema = getattr(mcp_tool, "inputSchema", None) or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])

    if not properties:
        return None

    fields = {}
    for name in properties.keys():
        default = ... if name in required else None
        fields[name] = (Any, default)

    model_name = f"{mcp_tool.name}Args"
    return create_model(model_name, **fields)


def _coerce_uid(
    arguments_dict: Dict[str, Any],
    args: tuple[Any, ...],
    kwargs: Dict[str, Any],
) -> str | None:
    """Best-effort UID extraction from mixed tool input shapes."""
    uid_value = arguments_dict.get("uid")
    if uid_value:
        return str(uid_value)

    uid_value = arguments_dict.get("dashboardUid") or arguments_dict.get("dashboard_uid")
    if uid_value:
        return str(uid_value)

    if args:
        if len(args) == 1:
            raw = args[0]
            if isinstance(raw, dict):
                uid_value = raw.get("uid") or raw.get("dashboardUid") or raw.get("dashboard_uid")
                if uid_value:
                    return str(uid_value)
            elif isinstance(raw, str) and raw.strip():
                return raw.strip()

    raw = kwargs.get("uid")
    if isinstance(raw, dict):
        uid_value = raw.get("uid")
        if uid_value:
            return str(uid_value)
    elif isinstance(raw, str) and raw.strip():
        return raw.strip()

    return None


def _extract_prometheus_uid(data: Any) -> str | None:
    """Find a Prometheus datasource UID from list_datasources result."""
    try:
        # Handle MCP TextContent objects - extract text and parse JSON
        if isinstance(data, list) and data and hasattr(data[0], 'text'):
            # Parse the JSON from the text content
            text = data[0].text
            parsed = json.loads(text) if isinstance(text, str) else text
            if isinstance(parsed, dict):
                data = parsed

        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # common MCP shape might wrap in "datasources"
            if "datasources" in data and isinstance(data["datasources"], list):
                items = data["datasources"]
            elif "items" in data and isinstance(data["items"], list):
                items = data["items"]

        for item in items:
            if not isinstance(item, dict):
                continue
            ds_type = item.get("type") or item.get("datasource_type")
            if ds_type and "prometheus" in str(ds_type).lower():
                uid = item.get("uid") or item.get("id")
                if uid:
                    return uid
    except Exception:
        return None
    return None


def _fallback_get_dashboard_summary(uid: str) -> Dict[str, Any] | None:
    """Fallback summary builder using Grafana HTTP API when MCP call fails."""
    grafana_url = os.getenv("GRAFANA_URL")
    grafana_token = os.getenv("GRAFANA_TOKEN")
    if not grafana_url or not grafana_token:
        logger.warning(
            "Fallback summary skipped: missing Grafana env vars",
            extra={"grafana_url_set": bool(grafana_url), "grafana_token_set": bool(grafana_token)},
        )
        return None

    url = f"{grafana_url.rstrip('/')}/api/dashboards/uid/{uid}"
    headers = {"Authorization": f"Bearer {grafana_token}"}

    try:
        resp = httpx.get(url, headers=headers, timeout=10)
    except Exception:
        logger.warning("Fallback summary failed: request error", extra={"uid": uid})
        return None

    if resp.status_code != 200:
        logger.warning(
            f"Fallback summary failed: non-200 response ({resp.status_code}) for uid={uid} url={url}"
        )
        return None

    data = resp.json()
    dashboard = data.get("dashboard") or {}
    meta = data.get("meta") or {}

    panels = dashboard.get("panels") or []
    panel_summaries = []
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        targets = panel.get("targets") or []
        panel_summaries.append({
            "id": panel.get("id"),
            "title": panel.get("title", ""),
            "type": panel.get("type", ""),
            "description": panel.get("description", ""),
            "queryCount": len(targets) if isinstance(targets, list) else 0,
        })

    variables = []
    templating = dashboard.get("templating") or {}
    for variable in templating.get("list") or []:
        if not isinstance(variable, dict):
            continue
        variables.append({
            "name": variable.get("name", ""),
            "type": variable.get("type", ""),
            "label": variable.get("label", ""),
        })

    time_range = dashboard.get("time") or {}

    return {
        "uid": dashboard.get("uid", uid),
        "title": dashboard.get("title", ""),
        "description": dashboard.get("description", ""),
        "tags": dashboard.get("tags", []),
        "panelCount": len(panel_summaries),
        "panels": panel_summaries,
        "variables": variables,
        "timeRange": {"from": time_range.get("from", ""), "to": time_range.get("to", "")},
        "refresh": dashboard.get("refresh"),
        "meta": meta,
    }


async def build_mcp_tools(settings: Settings) -> List[Tool]:
    """
    Dynamically discover and create LangChain Tool definitions from MCP server.

    This connects to the Grafana MCP server and discovers all available tools,
    then wraps them as LangChain tools that the agent can use.
    """
    client = MCPClient(settings=settings)

    try:
        # Connect to MCP server
        await client.connect()
        logger.info("Connected to MCP server for tool discovery")

        # Discover all available tools from the MCP server
        tools_response = await client.session.list_tools()
        logger.info(f"Discovered {len(tools_response.tools)} tools from MCP server")

        langchain_tools = []

        for mcp_tool in tools_response.tools:
            # Create a closure that captures the tool name and client
            def make_tool_func(tool_name: str):
                async def tool_func(*args: Any, **kwargs: Any) -> str:
                    """
                    Execute an MCP tool with the given input.

                    Args:
                        args: optional positional tool arguments
                        kwargs: dict of tool arguments

                    Returns:
                        Formatted string result from the MCP tool
                    """
                    try:
                        # Normalize arguments
                        arguments_dict: Dict[str, Any] = {}
                        if args:
                            if len(args) == 1:
                                arguments = args[0]
                                if isinstance(arguments, dict):
                                    arguments_dict = arguments
                                elif isinstance(arguments, str):
                                    cleaned = arguments.strip()
                                    if cleaned.startswith("{"):
                                        arguments_dict = json.loads(cleaned)
                                    elif cleaned:
                                        arguments_dict = {"input": cleaned}
                                    else:
                                        arguments_dict = {}
                                else:
                                    return "Error: Unsupported argument type"
                            else:
                                return "Error: Unsupported positional arguments"
                        elif "arguments" in kwargs and len(kwargs) == 1:
                            arguments = kwargs.get("arguments")
                            if arguments is None:
                                arguments_dict = {}
                            elif isinstance(arguments, dict):
                                arguments_dict = arguments
                            elif isinstance(arguments, str):
                                cleaned = arguments.strip()
                                if cleaned.startswith("{"):
                                    arguments_dict = json.loads(cleaned)
                                elif cleaned:
                                    arguments_dict = {"input": cleaned}
                                else:
                                    arguments_dict = {}
                            else:
                                return "Error: Unsupported argument type"
                        else:
                            arguments_dict = kwargs
                        if tool_name == "get_dashboard_summary":
                            logger.info(
                                "Dashboard summary raw arguments",
                                extra={
                                    "args": args,
                                    "kwargs": kwargs,
                                    "arguments_dict": arguments_dict,
                                },
                            )

                        if "datasource_uid" in arguments_dict and "datasourceUid" not in arguments_dict:
                            arguments_dict["datasourceUid"] = arguments_dict.pop("datasource_uid")

                        if "uid" not in arguments_dict and "input" in arguments_dict:
                            if tool_name in {
                                "get_dashboard_summary",
                                "get_dashboard_by_uid",
                                "get_dashboard_property",
                                "get_dashboard_panel_queries",
                            }:
                                arguments_dict["uid"] = arguments_dict.pop("input")

                        # Auto-select Prometheus datasource if missing
                        if tool_name == "list_prometheus_metric_names" and "datasourceUid" not in arguments_dict:
                            ds_result = await client.invoke_tool("list_datasources", {})
                            prom_uid = _extract_prometheus_uid(ds_result)
                            if prom_uid:
                                arguments_dict["datasourceUid"] = prom_uid

                        if tool_name == "get_dashboard_summary":
                            uid_value = _coerce_uid(arguments_dict, args, kwargs) or ""
                            if uid_value and "uid" not in arguments_dict:
                                arguments_dict["uid"] = uid_value
                            if uid_value:
                                fallback = _fallback_get_dashboard_summary(uid_value)
                                if fallback is not None:
                                    logger.info(
                                        "Using direct Grafana API for dashboard summary",
                                        extra={"uid": uid_value}
                                    )
                                    return formatter.format(tool_name, fallback)

                        arguments_dict = _normalize_query_arguments(tool_name, arguments_dict)
                        logger.info(f"Invoking MCP tool: {tool_name}", extra={"arguments": arguments_dict})
                        # Use a fresh MCP client per call to avoid cross-task teardown issues.
                        call_client = MCPClient(settings=settings)
                        try:
                            try:
                                result = await call_client.invoke_tool(tool_name, arguments_dict)
                            except Exception as e:
                                if _should_retry_query_error(e):
                                    retry_args = _normalize_query_arguments(
                                        tool_name,
                                        arguments_dict,
                                        force_step_seconds=True
                                    )
                                    logger.info(
                                        "Retrying MCP tool with normalized arguments",
                                        extra={"tool": tool_name, "arguments": retry_args}
                                    )
                                    result = await call_client.invoke_tool(tool_name, retry_args)
                                else:
                                    raise
                        finally:
                            await call_client.disconnect()

                        # Use structured formatter for better LLM comprehension
                        formatted_result = formatter.format(tool_name, result)

                        logger.debug(f"Tool {tool_name} completed", extra={
                            "result_length": len(formatted_result)
                        })

                        return formatted_result

                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse tool input as JSON: {e}")
                        return f"Error: Invalid JSON input - {str(e)}"
                    except Exception as e:
                        if tool_name == "get_dashboard_summary":
                            fallback = _fallback_get_dashboard_summary(
                                arguments_dict.get("uid", "")
                            )
                            if fallback is not None:
                                logger.warning(
                                    "Falling back to direct Grafana API for dashboard summary",
                                    extra={"uid": arguments_dict.get("uid", "")}
                                )
                                return formatter.format(tool_name, fallback)

                        logger.error(f"Tool execution failed: {e}", extra={"tool": tool_name})
                        return f"Error executing {tool_name}: {str(e)}"
                return tool_func

            # Create the tool function with closure
            tool_func = make_tool_func(mcp_tool.name)
            args_schema = _build_args_schema(mcp_tool)

            # Build description with parameter info if available
            description = mcp_tool.description or f"Execute {mcp_tool.name}"
            if hasattr(mcp_tool, 'inputSchema') and mcp_tool.inputSchema:
                schema = mcp_tool.inputSchema
                if 'properties' in schema:
                    params = ', '.join(schema['properties'].keys())
                    description += f"\n\nParameters: {params}"
                if 'required' in schema:
                    required = ', '.join(schema['required'])
                    description += f"\n\nRequired: {required}"

            # Create LangChain Tool
            # Use coroutine parameter for async functions
            tool_kwargs = {
                "coroutine": tool_func,
                "name": mcp_tool.name,
                "description": description,
            }
            if args_schema is not None:
                tool_kwargs["args_schema"] = args_schema
            langchain_tools.append(StructuredTool.from_function(**tool_kwargs))

        logger.info(f"Successfully created {len(langchain_tools)} LangChain tools")
        return langchain_tools

    except Exception as e:
        logger.error(f"Failed to discover MCP tools: {e}")
        # Return empty list if discovery fails - agent will still work without tools
        return []
    
    finally:
        # Always disconnect after tool discovery
        await client.disconnect()
        logger.info("Disconnected from MCP server after tool discovery")






