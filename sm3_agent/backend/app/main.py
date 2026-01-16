from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from backend.app.config import get_settings
from backend.app.mcp_servers import get_mcp_server_manager
from backend.agents.agent_manager import AgentManager
from backend.agents.proactive import create_default_targets, get_proactive_monitor
from backend.agents.customer_monitoring import get_customer_monitoring_manager
from backend.api.monitoring import router as monitoring_router
from backend.api.monitoring_v2 import router as monitoring_v2_router
from backend.api.alerts import router as alerts_router
from backend.api.mcp import router as mcp_router
from backend.schemas.models import ChatRequest, ChatResponse
from backend.telemetry.metrics import (
    chat_requests_total,
    chat_duration_seconds,
    active_sessions,
    get_metrics,
    get_content_type,
    set_agent_info,
    update_cache_metrics,
    update_monitoring_metrics
)
from backend.tools.cache import get_cache
from backend.tools.mcp_client import MCPClient
from backend.utils.logger import get_logger
import json
import asyncio
import time
from pydantic import BaseModel
from typing import List, Optional


settings = get_settings()
logger = get_logger(__name__)
agent_manager = AgentManager(settings=settings)
server_manager = get_mcp_server_manager()

# Store MCP client in app state
mcp_client_instance = None

app = FastAPI(
    title="Grafana MCP Chat API",
    version="0.2.0",
    description="Chat agent for Grafana observability with proactive monitoring and anomaly detection"
)

# Configure CORS with settings from environment
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "OPTIONS", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# Include routers
app.include_router(monitoring_router)  # Legacy v1 monitoring
app.include_router(monitoring_v2_router)  # New multi-customer monitoring (v2)
app.include_router(alerts_router, prefix="/api")
app.include_router(mcp_router)


@app.on_event("startup")
async def startup_event():
    """Initialize agent and proactive monitoring on startup."""
    logger.info("Starting Grafana MCP Chat API v0.2.0")
    logger.info(f"CORS origins: {settings.cors_origins}")
    logger.info(f"MCP server URL: {settings.mcp_server_url}")
    if settings.mcp_server_urls:
        logger.info(f"Additional MCP servers: {settings.mcp_server_urls}")
    logger.info(f"MCP execution mode: {settings.mcp_execution_mode}")

    # Set agent info for Prometheus
    set_agent_info(
        version="0.2.0",
        model=settings.model,
        mcp_server=settings.mcp_server_url
    )

    # Initialize agent
    await agent_manager.initialize()
    logger.info("Agent initialized successfully")

    # Initialize proactive monitoring (but don't start it yet)
    try:
        mcp_client = MCPClient(settings=settings)
        await mcp_client.connect()

        proactive_monitor = get_proactive_monitor(mcp_client)

        # Add default monitoring targets (optional - can be configured via API)
        default_targets = create_default_targets()
        for target in default_targets:
            # Disable by default - user can enable via API
            target.enabled = False
            proactive_monitor.add_target(target)

        logger.info(f"Proactive monitoring initialized with {len(default_targets)} default targets")
        logger.info("Use POST /monitoring/start to begin proactive monitoring")

    except Exception as e:
        logger.warning(f"Proactive monitoring initialization failed: {e}")
        logger.warning("Proactive monitoring will not be available")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    """
    Handle chat requests from the UI.

    Args:
        payload: Chat request with message and optional session_id

    Returns:
        ChatResponse with agent's message, tool calls, and suggestions
    """
    session_id = payload.session_id or "default"
    start_time = time.time()
    status = "success"

    try:
        logger.info("Processing chat request", extra={"session_id": session_id})
        active_sessions.inc()

        result = await agent_manager.run_chat(message=payload.message, session_id=session_id)

        return ChatResponse(
            message=result.message,
            tool_calls=result.tool_calls,
            suggestions=result.suggestions
        )
    except Exception as e:
        status = "error"
        logger.error(f"Chat request failed: {e}", exc_info=True)
        raise
    finally:
        duration = time.time() - start_time
        chat_requests_total.labels(session_id=session_id, status=status).inc()
        chat_duration_seconds.labels(session_id=session_id).observe(duration)
        active_sessions.dec()


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest):
    """
    Handle streaming chat requests with Server-Sent Events.

    Args:
        payload: Chat request with message and optional session_id

    Returns:
        StreamingResponse with SSE events
    """
    logger.info("Processing streaming chat request", extra={"session_id": payload.session_id})

    async def event_generator():
        """Generate SSE events for streaming response."""
        try:
            # Send initial event
            yield f"data: {json.dumps({'type': 'start', 'message': 'Processing your request...'})}\n\n"
            await asyncio.sleep(0.1)  # Small delay for client to connect

            # Stream the agent response
            async for chunk in agent_manager.run_chat_stream(
                message=payload.message,
                session_id=payload.session_id
            ):
                if chunk["type"] == "token":
                    yield f"data: {json.dumps(chunk)}\n\n"
                elif chunk["type"] == "tool":
                    yield f"data: {json.dumps(chunk)}\n\n"
                elif chunk["type"] == "error":
                    yield f"data: {json.dumps(chunk)}\n\n"
                    break
                elif chunk["type"] == "complete":
                    yield f"data: {json.dumps(chunk)}\n\n"
                    break

                await asyncio.sleep(0.01)  # Small delay to prevent overwhelming client

        except Exception as e:
            logger.error(f"Streaming error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        # Send completion event
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "grafana-mcp-chat"}


@app.get("/metrics")
async def metrics():
    """
    Prometheus metrics endpoint.

    Exposes metrics for monitoring agent performance, usage, and health.
    """
    # Update cache metrics
    cache = get_cache()
    update_cache_metrics(cache.get_stats())

    # Update monitoring metrics if available
    try:
        monitor = get_proactive_monitor()
        update_monitoring_metrics(monitor.get_monitoring_status())
    except:
        pass  # Monitoring might not be initialized

    return Response(content=get_metrics(), media_type=get_content_type())


@app.get("/cache/stats")
async def cache_stats() -> dict:
    """
    Get cache statistics.

    Returns:
        Cache performance metrics including hit rate, size, etc.
    """
    cache = get_cache()
    return cache.get_stats()


@app.post("/cache/clear")
async def clear_cache() -> dict:
    """
    Clear all cache entries.

    Returns:
        Confirmation message
    """
    cache = get_cache()
    stats_before = cache.get_stats()
    cache.clear()

    logger.info("Cache cleared via API")
    return {
        "status": "cleared",
        "entries_removed": stats_before["size"]
    }


# ============================================================================
# Customer/MCP Server Management API
# ============================================================================

class MCPServerInfo(BaseModel):
    """Response model for an MCP server."""
    type: str
    url: str


class CustomerInfo(BaseModel):
    """Response model for a customer."""
    name: str
    description: str
    host: str
    mcp_servers: List[MCPServerInfo]


# Keep old names for backwards compatibility
class GrafanaServerInfo(BaseModel):
    """Response model for a Grafana server (backwards compatibility)."""
    name: str
    url: str
    description: str


class CustomersResponse(BaseModel):
    """Response model for list of customers."""
    customers: List[CustomerInfo]
    current: Optional[str] = None
    default: Optional[str] = None


# Keep old response model for backwards compatibility
class GrafanaServersResponse(BaseModel):
    """Response model for list of Grafana servers (backwards compatibility)."""
    servers: List[GrafanaServerInfo]
    current: Optional[str] = None
    default: Optional[str] = None


class SwitchServerRequest(BaseModel):
    """Request model for switching servers (backwards compatibility)."""
    server_name: str


class SwitchCustomerRequest(BaseModel):
    """Request model for switching customer."""
    customer_name: str


class SwitchServerResponse(BaseModel):
    """Response model for switching servers."""
    success: bool
    server_name: str
    server_url: Optional[str] = None
    message: str
    mcp_server_count: Optional[int] = None
    connected_mcps: Optional[List[str]] = None
    failed_mcps: Optional[List[str]] = None
    tool_count: Optional[int] = None
    is_starting: bool = False  # True if containers are still starting


class ContainerHealthStatus(BaseModel):
    """Health status for a single MCP container."""
    mcp_type: str
    state: str
    container_id: Optional[str] = None
    error_message: Optional[str] = None
    uptime_seconds: Optional[float] = None


class CustomerContainersHealth(BaseModel):
    """Health status for all containers of a customer."""
    customer_name: str
    all_healthy: bool
    containers: List[ContainerHealthStatus]


@app.get("/api/customers", response_model=CustomersResponse)
async def list_customers() -> CustomersResponse:
    """
    List all available customers with their MCP servers.

    Returns:
        List of configured customers with current selection
    """
    customers = [
        CustomerInfo(
            name=c.name,
            description=c.description,
            host=c.host,
            mcp_servers=[MCPServerInfo(type=s.type, url=s.url) for s in c.mcp_servers]
        )
        for c in server_manager.config.customers
    ]
    
    default_customer = server_manager.get_default()
    
    return CustomersResponse(
        customers=customers,
        current=agent_manager.get_current_server_name(),
        default=default_customer.name if default_customer else None
    )


# Backwards compatibility endpoint
@app.get("/api/grafana-servers", response_model=GrafanaServersResponse)
async def list_grafana_servers() -> GrafanaServersResponse:
    """
    List all available Grafana servers (backwards compatibility).
    Use /api/customers for the new multi-MCP server format.

    Returns:
        List of configured Grafana servers with current selection
    """
    servers = [
        GrafanaServerInfo(
            name=c.name,
            url=c.get_server_by_type("grafana").url if c.get_server_by_type("grafana") else "",
            description=c.description
        )
        for c in server_manager.config.customers
        if c.get_server_by_type("grafana")
    ]
    
    default_customer = server_manager.get_default()
    
    return GrafanaServersResponse(
        servers=servers,
        current=agent_manager.get_current_server_name(),
        default=default_customer.name if default_customer else None
    )


@app.post("/api/customers/switch", response_model=SwitchServerResponse)
async def switch_customer(request: SwitchCustomerRequest) -> SwitchServerResponse:
    """
    Switch to a different customer (activates all their MCP servers).

    This starts containers on-demand for the customer's MCP servers,
    waits for health checks, and returns the status.

    Args:
        request: Contains the customer_name to switch to

    Returns:
        Success status with connected MCP types and tool count
    """
    customer = server_manager.get_customer(request.customer_name)
    
    if not customer:
        return SwitchServerResponse(
            success=False,
            server_name=request.customer_name,
            message=f"Unknown customer: {request.customer_name}"
        )
    
    try:
        result = await agent_manager.switch_customer(request.customer_name)
        grafana_server = customer.get_server_by_type("grafana")
        
        logger.info(
            f"Switch to customer {request.customer_name}: success={result.success}, "
            f"connected={result.connected_mcps}, failed={result.failed_mcps}, tools={result.tool_count}"
        )
        
        return SwitchServerResponse(
            success=result.success,
            server_name=request.customer_name,
            server_url=grafana_server.url if grafana_server else None,
            message=result.message,
            mcp_server_count=len(customer.mcp_servers),
            connected_mcps=result.connected_mcps,
            failed_mcps=result.failed_mcps,
            tool_count=result.tool_count,
            is_starting=result.is_starting
        )
            
    except Exception as e:
        logger.error(f"Error switching customer: {e}", exc_info=True)
        return SwitchServerResponse(
            success=False,
            server_name=request.customer_name,
            message=f"Error: {str(e)}"
        )


# Backwards compatibility endpoint
@app.post("/api/grafana-servers/switch", response_model=SwitchServerResponse)
async def switch_grafana_server(request: SwitchServerRequest) -> SwitchServerResponse:
    """
    Switch to a different Grafana server (backwards compatibility).
    Use /api/customers/switch for the new multi-MCP format.

    Args:
        request: Contains the server_name to switch to

    Returns:
        Success status and new server details
    """
    customer = server_manager.get_customer(request.server_name)
    
    if not customer:
        return SwitchServerResponse(
            success=False,
            server_name=request.server_name,
            message=f"Unknown server: {request.server_name}"
        )
    
    try:
        success = await agent_manager.switch_customer(request.server_name)
        grafana_server = customer.get_server_by_type("grafana")
        
        if success:
            logger.info(f"Switched to customer: {request.server_name} ({grafana_server.url if grafana_server else 'N/A'})")
            return SwitchServerResponse(
                success=True,
                server_name=request.server_name,
                server_url=grafana_server.url if grafana_server else None,
                message=f"Successfully connected to {request.server_name}",
                mcp_server_count=len(customer.mcp_servers)
            )
        else:
            return SwitchServerResponse(
                success=False,
                server_name=request.server_name,
                message=f"Failed to switch to {request.server_name}"
            )
            
    except Exception as e:
        logger.error(f"Error switching server: {e}", exc_info=True)
        return SwitchServerResponse(
            success=False,
            server_name=request.server_name,
            message=f"Error: {str(e)}"
        )


# =============================================================================
# Container Health Endpoints
# =============================================================================

@app.get("/api/containers/health/{customer_name}", response_model=CustomerContainersHealth)
async def get_customer_container_health(customer_name: str) -> CustomerContainersHealth:
    """
    Get health status of all MCP containers for a customer.
    
    Args:
        customer_name: Name of the customer
        
    Returns:
        Health status for each MCP container
    """
    try:
        from backend.containers import get_container_manager, ContainerState, DOCKER_AVAILABLE
        
        if not DOCKER_AVAILABLE:
            return CustomerContainersHealth(
                customer_name=customer_name,
                all_healthy=False,
                containers=[]
            )
        
        container_manager = get_container_manager()
        customer_status = container_manager.get_customer_status(customer_name)
        
        if not customer_status:
            return CustomerContainersHealth(
                customer_name=customer_name,
                all_healthy=False,
                containers=[]
            )
        
        container_statuses = [
            ContainerHealthStatus(
                mcp_type=mcp_type.value,
                state=status.state.value,
                container_id=status.container_id[:12] if status.container_id else None,
                error_message=status.error_message,
                uptime_seconds=status.uptime_seconds
            )
            for mcp_type, status in customer_status.containers.items()
        ]
        
        return CustomerContainersHealth(
            customer_name=customer_name,
            all_healthy=customer_status.all_healthy(),
            containers=container_statuses
        )
        
    except Exception as e:
        logger.error(f"Error getting container health for {customer_name}: {e}")
        return CustomerContainersHealth(
            customer_name=customer_name,
            all_healthy=False,
            containers=[]
        )


@app.get("/api/containers/active")
async def get_active_containers():
    """
    Get list of customers with active (warm) containers.
    
    Returns:
        List of customer names with active containers
    """
    try:
        from backend.containers import get_container_manager, DOCKER_AVAILABLE
        
        if not DOCKER_AVAILABLE:
            return {
                "active_customers": [],
                "max_warm": 3,
                "count": 0,
                "docker_available": False
            }
        
        container_manager = get_container_manager()
        active_customers = container_manager.get_active_customers()
        
        return {
            "active_customers": active_customers,
            "max_warm": container_manager._max_warm,
            "count": len(active_customers)
        }
        
    except Exception as e:
        logger.error(f"Error getting active containers: {e}")
        return {
            "active_customers": [],
            "max_warm": 3,
            "count": 0,
            "error": str(e)
        }


@app.post("/api/containers/cleanup")
async def cleanup_orphaned_containers():
    """
    Clean up orphaned SM3 containers that are no longer managed.
    
    Returns:
        Number of containers removed
    """
    try:
        from backend.containers import get_container_manager, DOCKER_AVAILABLE
        
        if not DOCKER_AVAILABLE:
            return {
                "success": False,
                "removed_count": 0,
                "error": "Docker SDK not available"
            }
        
        container_manager = get_container_manager()
        removed = container_manager.cleanup_orphaned_containers()
        
        return {
            "success": True,
            "removed_count": removed,
            "message": f"Removed {removed} orphaned container(s)"
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up containers: {e}")
        return {
            "success": False,
            "removed_count": 0,
            "error": str(e)
        }
