from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import httpx

from langchain.agents import Tool
from langchain.tools import StructuredTool
from pydantic import create_model

from backend.app.config import Settings
from backend.app.runtime import get_execution_mode
from backend.tools.mcp_client import MCPClient
from backend.tools.result_formatter import ToolResultFormatter
from backend.utils.logger import get_logger

# Import for type hints - avoid circular import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from backend.app.mcp_servers import MCPServer


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


def _current_time_rfc3339() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_query_arguments(
    tool_name: str,
    arguments: Dict[str, Any],
    force_step_seconds: bool = False
) -> Dict[str, Any]:
    """Apply defaults for query tools to avoid common MCP errors."""
    if tool_name not in {"query_prometheus", "query_loki_logs"}:
        return arguments

    updated = dict(arguments)
    for key in ("startTime", "endTime", "startRfc3339", "endRfc3339"):
        if key in updated and isinstance(updated[key], str) and not updated[key].strip():
            updated.pop(key)

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

        if "startTime" in updated and "endTime" not in updated:
            updated["endTime"] = _current_time_rfc3339()

    if tool_name == "query_loki_logs":
        for key in ("startRfc3339", "endRfc3339"):
            raw = updated.get(key)
            if isinstance(raw, str):
                resolved = _resolve_relative_time(raw)
                if resolved:
                    updated[key] = resolved

        if "startRfc3339" in updated and "endRfc3339" not in updated:
            updated["endRfc3339"] = _current_time_rfc3339()

    return updated


def _should_retry_query_error(error: Exception) -> bool:
    message = str(error).lower()
    return (
        "stepseconds must be provided" in message
        or "parsing start time" in message
        or "cannot parse \"now" in message
    )


def _get_mcp_servers(settings: Settings) -> List[Dict[str, Any]]:
    urls = list(settings.mcp_server_urls) if settings.mcp_server_urls else []
    primary_url = settings.mcp_server_url
    if primary_url and primary_url not in urls:
        urls.insert(0, primary_url)

    names = list(settings.mcp_server_names) if settings.mcp_server_names else []
    servers = []
    seen_names: set[str] = set()

    for idx, url in enumerate(urls):
        name = names[idx] if idx < len(names) and names[idx] else None
        if not name:
            name = "grafana" if url == primary_url else f"mcp{idx + 1}"

        base_name = name
        suffix = 1
        while name in seen_names:
            suffix += 1
            name = f"{base_name}{suffix}"

        seen_names.add(name)
        servers.append({"name": name, "url": url, "primary": url == primary_url})

    return servers


def _extract_command(arguments: Dict[str, Any]) -> Optional[str]:
    for key in ("command", "cmd", "commandLine"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    args_value = arguments.get("args") or arguments.get("arguments")
    if isinstance(args_value, list):
        return " ".join(str(part) for part in args_value if part is not None).strip() or None
    if isinstance(args_value, str) and args_value.strip():
        return args_value.strip()

    return None


def _is_command_allowed(command: str, allowlist: List[str]) -> bool:
    if not command:
        return False
    base = command.strip().split()[0].lower()
    return base in {item.lower() for item in allowlist}


def _write_audit_event(settings: Settings, event: Dict[str, Any]) -> None:
    try:
        audit_dir = Path(settings.mcp_audit_dir)
        audit_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        audit_file = audit_dir / f"mcp-audit-{timestamp}.jsonl"
        with audit_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=str) + "\n")
    except Exception as exc:
        logger.warning(f"Failed to write MCP audit log: {exc}")


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
    try:
        servers = _get_mcp_servers(settings)
        langchain_tools: List[Tool] = []

        for server in servers:
            server_name = server["name"]
            server_url = server["url"]
            is_primary = server["primary"]

            client = MCPClient(
                settings=settings,
                server_url=server_url,
                cache_namespace=server_name
            )

            try:
                await client.connect()
                logger.info(
                    "Connected to MCP server for tool discovery",
                    extra={"server": server_name, "url": server_url}
                )

                tools_response = await client.session.list_tools()
                logger.info(
                    f"Discovered {len(tools_response.tools)} tools from MCP server",
                    extra={"server": server_name}
                )

            except Exception as e:
                logger.error(
                    f"Failed to discover MCP tools for server {server_name}: {e}"
                )
                await client.disconnect()
                continue

            for mcp_tool in tools_response.tools:
                display_name = mcp_tool.name if is_primary else f"{server_name}__{mcp_tool.name}"

                # Create a closure that captures the tool name and server config
                def make_tool_func(
                    tool_name: str,
                    display_name: str,
                    server_name: str,
                    server_url: str,
                    is_primary: bool,
                ):
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
                            command: Optional[str] = None
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

                            # Auto-select Prometheus datasource if missing (Grafana MCP only)
                            if is_primary and tool_name == "list_prometheus_metric_names" and "datasourceUid" not in arguments_dict:
                                temp_client = MCPClient(
                                    settings=settings,
                                    server_url=server_url,
                                    cache_namespace=server_name
                                )
                                try:
                                    ds_result = await temp_client.invoke_tool("list_datasources", {})
                                finally:
                                    await temp_client.disconnect()
                                prom_uid = _extract_prometheus_uid(ds_result)
                                if prom_uid:
                                    arguments_dict["datasourceUid"] = prom_uid

                            if is_primary and tool_name == "get_dashboard_summary":
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

                            command = _extract_command(arguments_dict)
                            if command:
                                allowlist = settings.mcp_command_allowlist
                                is_allowed = _is_command_allowed(command, allowlist)
                                event = {
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "server": server_name,
                                    "tool": display_name,
                                    "command": command,
                                    "allowed": is_allowed,
                                    "mode": get_execution_mode(),
                                    "arguments": arguments_dict,
                                }

                                if not is_allowed:
                                    event["status"] = "blocked"
                                    _write_audit_event(settings, event)
                                    return (
                                        f"Command blocked by policy. "
                                        f"Allowed commands: {', '.join(allowlist)}"
                                    )

                                if get_execution_mode() == "suggest":
                                    event["status"] = "suggested"
                                    _write_audit_event(settings, event)
                                    return (
                                        "Command execution is disabled (suggest-only mode). "
                                        f"Suggested command: `{command}`"
                                    )

                            arguments_dict = _normalize_query_arguments(tool_name, arguments_dict)
                            logger.info(
                                f"Invoking MCP tool: {display_name}",
                                extra={"arguments": arguments_dict, "server": server_name}
                            )
                            # Use a fresh MCP client per call to avoid cross-task teardown issues.
                            call_client = MCPClient(
                                settings=settings,
                                server_url=server_url,
                                cache_namespace=server_name
                            )
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

                            if command:
                                _write_audit_event(
                                    settings,
                                    {
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                        "server": server_name,
                                        "tool": display_name,
                                        "command": command,
                                        "allowed": True,
                                        "mode": get_execution_mode(),
                                        "status": "executed",
                                        "arguments": arguments_dict,
                                    },
                                )

                            return formatted_result

                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse tool input as JSON: {e}")
                            return f"Error: Invalid JSON input - {str(e)}"
                        except Exception as e:
                            if is_primary and tool_name == "get_dashboard_summary":
                                fallback = _fallback_get_dashboard_summary(
                                    arguments_dict.get("uid", "")
                                )
                                if fallback is not None:
                                    logger.warning(
                                        "Falling back to direct Grafana API for dashboard summary",
                                        extra={"uid": arguments_dict.get("uid", "")}
                                    )
                                    return formatter.format(tool_name, fallback)

                            if command:
                                _write_audit_event(
                                    settings,
                                    {
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                        "server": server_name,
                                        "tool": display_name,
                                        "command": command,
                                        "allowed": True,
                                        "mode": get_execution_mode(),
                                        "status": "failed",
                                        "error": str(e),
                                        "arguments": arguments_dict,
                                    },
                                )

                            logger.error(
                                f"Tool execution failed: {e}",
                                extra={"tool": display_name, "server": server_name}
                            )
                            return f"Error executing {display_name}: {str(e)}"

                    return tool_func

                # Create the tool function with closure
                tool_func = make_tool_func(
                    mcp_tool.name,
                    display_name,
                    server_name,
                    server_url,
                    is_primary
                )
                args_schema = _build_args_schema(mcp_tool)

                # Build description with parameter info if available
                description = mcp_tool.description or f"Execute {mcp_tool.name}"
                description += f"\n\nMCP Server: {server_name}"
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
                    "name": display_name,
                    "description": description,
                }
                if args_schema is not None:
                    tool_kwargs["args_schema"] = args_schema
                langchain_tools.append(StructuredTool.from_function(**tool_kwargs))

            await client.disconnect()

        logger.info(f"Successfully created {len(langchain_tools)} LangChain tools")
        return langchain_tools

    except Exception as e:
        logger.error(f"Failed to discover MCP tools: {e}")
        # Return empty list if discovery fails - agent will still work without tools
        return []


async def build_mcp_tools_for_servers(
    settings: Settings,
    mcp_servers: List["MCPServer"]
) -> List[Tool]:
    """
    Build LangChain tools from a list of MCP servers for a customer.
    
    Each server type's tools are prefixed with the server type name
    (e.g., alertmanager__get_alerts, grafana__search_dashboards).
    The primary server (first Grafana) gets unprefixed tool names for compatibility.
    
    Args:
        settings: Application settings
        mcp_servers: List of MCPServer objects from a customer config
        
    Returns:
        List of LangChain tools from all MCP servers
    """
    langchain_tools: List[Tool] = []
    
    # Find the primary Grafana server (first one)
    primary_grafana_url = None
    for server in mcp_servers:
        if server.type == "grafana":
            primary_grafana_url = server.url
            break
    
    for mcp_server in mcp_servers:
        server_type = mcp_server.type
        server_url = mcp_server.url
        is_primary = (server_type == "grafana" and server_url == primary_grafana_url)
        
        client = MCPClient(
            settings=settings,
            server_url=server_url,
            cache_namespace=server_type
        )
        
        try:
            await client.connect()
            logger.info(
                f"Connected to {server_type} MCP server for tool discovery",
                extra={"type": server_type, "url": server_url}
            )
            
            tools_response = await client.session.list_tools()
            logger.info(
                f"Discovered {len(tools_response.tools)} tools from {server_type} MCP server"
            )
            
        except Exception as e:
            logger.error(
                f"Failed to discover tools for {server_type} MCP server at {server_url}: {e}"
            )
            await client.disconnect()
            continue
        
        for mcp_tool in tools_response.tools:
            # Primary Grafana tools keep original names for compatibility
            # Other servers get prefixed (e.g., alertmanager__get_alerts)
            if is_primary:
                display_name = mcp_tool.name
            else:
                display_name = f"{server_type}__{mcp_tool.name}"
            
            # Reuse the existing make_tool_func pattern
            def make_tool_func(
                tool_name: str,
                display_name: str,
                server_type: str,
                server_url: str,
                is_primary: bool,
            ):
                async def tool_func(*args: Any, **kwargs: Any) -> str:
                    """Execute an MCP tool with the given input."""
                    try:
                        command: Optional[str] = None
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
                        
                        # Grafana-specific argument normalization
                        if server_type == "grafana":
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
                            if is_primary and tool_name == "list_prometheus_metric_names" and "datasourceUid" not in arguments_dict:
                                temp_client = MCPClient(
                                    settings=settings,
                                    server_url=server_url,
                                    cache_namespace=server_type
                                )
                                try:
                                    ds_result = await temp_client.invoke_tool("list_datasources", {})
                                finally:
                                    await temp_client.disconnect()
                                prom_uid = _extract_prometheus_uid(ds_result)
                                if prom_uid:
                                    arguments_dict["datasourceUid"] = prom_uid

                            if is_primary and tool_name == "get_dashboard_summary":
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
                            
                            # Normalize query arguments for Prometheus/Loki
                            arguments_dict = _normalize_query_arguments(tool_name, arguments_dict)

                        # Command allowlist check (for SSH/Linux MCP servers)
                        command = _extract_command(arguments_dict)
                        if command:
                            allowlist = settings.mcp_command_allowlist
                            is_allowed = _is_command_allowed(command, allowlist)
                            event = {
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "server": server_type,
                                "tool": display_name,
                                "command": command,
                                "allowed": is_allowed,
                                "mode": get_execution_mode(),
                                "arguments": arguments_dict,
                            }

                            if not is_allowed:
                                event["status"] = "blocked"
                                _write_audit_event(settings, event)
                                return (
                                    f"Command blocked by policy. "
                                    f"Allowed commands: {', '.join(allowlist)}"
                                )

                            if get_execution_mode() == "suggest":
                                event["status"] = "suggested"
                                _write_audit_event(settings, event)
                                return (
                                    "Command execution is disabled (suggest-only mode). "
                                    f"Suggested command: `{command}`"
                                )

                        logger.info(
                            f"Invoking MCP tool: {display_name}",
                            extra={"arguments": arguments_dict, "server_type": server_type}
                        )
                        
                        # Use a fresh MCP client per call
                        call_client = MCPClient(
                            settings=settings,
                            server_url=server_url,
                            cache_namespace=server_type
                        )
                        try:
                            try:
                                result = await call_client.invoke_tool(tool_name, arguments_dict)
                            except Exception as e:
                                if server_type == "grafana" and _should_retry_query_error(e):
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

                        if command:
                            _write_audit_event(
                                settings,
                                {
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "server": server_type,
                                    "tool": display_name,
                                    "command": command,
                                    "allowed": True,
                                    "mode": get_execution_mode(),
                                    "status": "executed",
                                    "arguments": arguments_dict,
                                },
                            )

                        return formatted_result

                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse tool input as JSON: {e}")
                        return f"Error: Invalid JSON input - {str(e)}"
                    except Exception as e:
                        if server_type == "grafana" and is_primary and tool_name == "get_dashboard_summary":
                            fallback = _fallback_get_dashboard_summary(
                                arguments_dict.get("uid", "")
                            )
                            if fallback is not None:
                                logger.warning(
                                    "Falling back to direct Grafana API for dashboard summary",
                                    extra={"uid": arguments_dict.get("uid", "")}
                                )
                                return formatter.format(tool_name, fallback)

                        if command:
                            _write_audit_event(
                                settings,
                                {
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "server": server_type,
                                    "tool": display_name,
                                    "command": command,
                                    "allowed": True,
                                    "mode": get_execution_mode(),
                                    "status": "failed",
                                    "error": str(e),
                                    "arguments": arguments_dict,
                                },
                            )

                        logger.error(
                            f"Tool execution failed: {e}",
                            extra={"tool": display_name, "server_type": server_type}
                        )
                        return f"Error executing {display_name}: {str(e)}"

                return tool_func

            # Create the tool function with closure
            tool_func = make_tool_func(
                mcp_tool.name,
                display_name,
                server_type,
                server_url,
                is_primary
            )
            args_schema = _build_args_schema(mcp_tool)

            # Build description with parameter info
            description = mcp_tool.description or f"Execute {mcp_tool.name}"
            description += f"\n\nMCP Server Type: {server_type}"
            if hasattr(mcp_tool, 'inputSchema') and mcp_tool.inputSchema:
                schema = mcp_tool.inputSchema
                if 'properties' in schema:
                    params = ', '.join(schema['properties'].keys())
                    description += f"\n\nParameters: {params}"
                if 'required' in schema:
                    required = ', '.join(schema['required'])
                    description += f"\n\nRequired: {required}"

            # Create LangChain Tool
            tool_kwargs = {
                "coroutine": tool_func,
                "name": display_name,
                "description": description,
            }
            if args_schema is not None:
                tool_kwargs["args_schema"] = args_schema
            langchain_tools.append(StructuredTool.from_function(**tool_kwargs))
        
        await client.disconnect()
    
    logger.info(
        f"Successfully created {len(langchain_tools)} LangChain tools from {len(mcp_servers)} MCP servers"
    )
    return langchain_tools
