"""
Dynamic MCP Container Manager.

Manages Docker containers for MCP servers on-demand with LRU caching
to keep a configurable number of "warm" containers running.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# Docker SDK is optional - container management won't work without it
try:
    import docker
    from docker.errors import APIError, NotFound, ImageNotFound
    from docker.models.containers import Container
    DOCKER_AVAILABLE = True
except ImportError:
    docker = None  # type: ignore
    APIError = Exception  # type: ignore
    NotFound = Exception  # type: ignore
    ImageNotFound = Exception  # type: ignore
    Container = None  # type: ignore
    DOCKER_AVAILABLE = False

from backend.utils.logger import get_logger

logger = get_logger(__name__)


class ContainerState(Enum):
    """Container lifecycle states."""
    NOT_FOUND = "not_found"
    STARTING = "starting"
    RUNNING = "running"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class MCPType(Enum):
    """Supported MCP server types."""
    GRAFANA = "grafana"
    ALERTMANAGER = "alertmanager"
    GENESYS = "genesys"


@dataclass
class ContainerConfig:
    """Configuration for an MCP container."""
    customer_name: str
    mcp_type: MCPType
    image: str
    environment: Dict[str, str]
    port: int
    internal_port: int
    health_endpoint: str = "/mcp"
    
    @property
    def container_name(self) -> str:
        """Generate unique container name."""
        safe_name = self.customer_name.lower().replace(" ", "-").replace("[", "").replace("]", "")
        return f"sm3-mcp-{self.mcp_type.value}-{safe_name}"
    
    @property
    def url(self) -> str:
        """Get the MCP server URL."""
        if self.mcp_type == MCPType.GRAFANA:
            return f"http://localhost:{self.port}/mcp"
        else:
            return f"http://localhost:{self.port}/sse"


@dataclass
class ContainerStatus:
    """Status of a managed container."""
    config: ContainerConfig
    state: ContainerState
    container_id: Optional[str] = None
    started_at: Optional[float] = None
    last_accessed: float = field(default_factory=time.time)
    error_message: Optional[str] = None
    
    @property
    def uptime_seconds(self) -> float:
        """Get container uptime in seconds."""
        if self.started_at:
            return time.time() - self.started_at
        return 0


@dataclass
class CustomerContainers:
    """All containers for a customer."""
    customer_name: str
    containers: Dict[MCPType, ContainerStatus] = field(default_factory=dict)
    last_accessed: float = field(default_factory=time.time)
    
    def update_access_time(self) -> None:
        """Update the last access time."""
        self.last_accessed = time.time()
        for status in self.containers.values():
            status.last_accessed = time.time()
    
    def all_healthy(self) -> bool:
        """Check if all containers are healthy."""
        return all(s.state == ContainerState.HEALTHY for s in self.containers.values())
    
    def get_states(self) -> Dict[str, str]:
        """Get states of all containers."""
        return {t.value: s.state.value for t, s in self.containers.items()}


class MCPContainerManager:
    """
    Manages MCP Docker containers with LRU caching.
    
    Features:
    - On-demand container spawning when customer is selected
    - LRU cache to keep max N "warm" containers
    - Health checks before marking containers ready
    - Automatic cleanup of stale containers
    """
    
    _instance: Optional["MCPContainerManager"] = None
    
    def __new__(cls) -> "MCPContainerManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._docker: Optional[docker.DockerClient] = None
        self._customers: OrderedDict[str, CustomerContainers] = OrderedDict()
        self._max_warm: int = 3
        self._network_name: str = "sm3-mcp-network"
        self._health_timeout: int = 30
        self._health_interval: int = 2
        self._startup_timeout: int = 60
        
        # Port allocations (track which ports are in use)
        self._port_allocations: Dict[str, int] = {}  # container_name -> port
        self._port_ranges: Dict[MCPType, Tuple[int, int]] = {
            MCPType.GRAFANA: (3100, 8888),      # host_start, internal
            MCPType.ALERTMANAGER: (9100, 8080),
            MCPType.GENESYS: (9200, 8080),
        }
        
        # Image names
        self._images: Dict[MCPType, str] = {
            MCPType.GRAFANA: "grafana/mcp-grafana:latest",
            MCPType.ALERTMANAGER: "sm3/alertmanager-mcp:latest",
            MCPType.GENESYS: "sm3/genesys-mcp:latest",
        }
        
        self._initialized = True
        logger.info("MCPContainerManager initialized")
    
    def configure(
        self,
        max_warm: int = 3,
        network_name: str = "sm3-mcp-network",
        health_timeout: int = 30,
        health_interval: int = 2,
        startup_timeout: int = 60,
        port_ranges: Optional[Dict[str, Dict[str, int]]] = None,
        images: Optional[Dict[str, str]] = None,
    ) -> None:
        """Configure manager settings from config file."""
        self._max_warm = max_warm
        self._network_name = network_name
        self._health_timeout = health_timeout
        self._health_interval = health_interval
        self._startup_timeout = startup_timeout
        
        if port_ranges:
            for type_name, ports in port_ranges.items():
                try:
                    mcp_type = MCPType(type_name)
                    self._port_ranges[mcp_type] = (ports["start"], ports["internal"])
                except (ValueError, KeyError):
                    logger.warning(f"Invalid port range config for {type_name}")
        
        if images:
            for type_name, image in images.items():
                try:
                    mcp_type = MCPType(type_name)
                    self._images[mcp_type] = image
                except ValueError:
                    logger.warning(f"Invalid image config for {type_name}")
        
        logger.info(
            f"Container manager configured: max_warm={max_warm}, "
            f"network={network_name}, health_timeout={health_timeout}s"
        )
    
    @property
    def is_available(self) -> bool:
        """Check if Docker is available."""
        return DOCKER_AVAILABLE and self._docker is not None
    
    @property
    def docker(self):
        """Get Docker client, connecting if needed."""
        if not DOCKER_AVAILABLE:
            raise RuntimeError("Docker SDK not installed. Install with: pip install docker")
        if self._docker is None:
            try:
                self._docker = docker.from_env()
                self._docker.ping()
                logger.info("Connected to Docker daemon")
            except Exception as e:
                logger.error(f"Failed to connect to Docker: {e}")
                raise RuntimeError(f"Docker not available: {e}")
        return self._docker
    
    def _ensure_network(self) -> None:
        """Ensure the Docker network exists."""
        try:
            self.docker.networks.get(self._network_name)
        except NotFound:
            logger.info(f"Creating Docker network: {self._network_name}")
            self.docker.networks.create(self._network_name, driver="bridge")
    
    def _allocate_port(self, mcp_type: MCPType, container_name: str) -> int:
        """Allocate a port for a container."""
        # Check if already allocated
        if container_name in self._port_allocations:
            return self._port_allocations[container_name]
        
        base_port, _ = self._port_ranges[mcp_type]
        used_ports = set(self._port_allocations.values())
        
        # Find next available port in range
        for offset in range(100):  # Allow 100 ports per type
            port = base_port + offset
            if port not in used_ports:
                self._port_allocations[container_name] = port
                return port
        
        raise RuntimeError(f"No available ports for {mcp_type.value}")
    
    def _release_port(self, container_name: str) -> None:
        """Release a port allocation."""
        self._port_allocations.pop(container_name, None)
    
    def _build_container_config(
        self,
        customer_name: str,
        mcp_type: MCPType,
        server_config: Dict[str, Any],
    ) -> ContainerConfig:
        """Build container configuration from MCP server config."""
        config = server_config.get("config", {})
        image = self._images[mcp_type]
        _, internal_port = self._port_ranges[mcp_type]
        
        # Build environment variables
        environment: Dict[str, str] = {}
        
        if mcp_type == MCPType.GRAFANA:
            environment["GRAFANA_URL"] = config.get("grafana_url", "")
            token_env = config.get("token_env", "")
            if token_env:
                environment["GRAFANA_SERVICE_ACCOUNT_TOKEN"] = os.environ.get(token_env, "")
                environment["GRAFANA_TOKEN"] = os.environ.get(token_env, "")
        
        elif mcp_type == MCPType.ALERTMANAGER:
            environment["ALERTMANAGER_URL"] = config.get("alertmanager_url", "")
            environment["MCP_TRANSPORT"] = "sse"
        
        elif mcp_type == MCPType.GENESYS:
            environment["GENESYSCLOUD_REGION"] = config.get("region", "mypurecloud.com")
            client_id_env = config.get("client_id_env", "")
            client_secret_env = config.get("client_secret_env", "")
            if client_id_env:
                environment["GENESYSCLOUD_OAUTHCLIENT_ID"] = os.environ.get(client_id_env, "")
            if client_secret_env:
                environment["GENESYSCLOUD_OAUTHCLIENT_SECRET"] = os.environ.get(client_secret_env, "")
        
        # Create config
        temp_config = ContainerConfig(
            customer_name=customer_name,
            mcp_type=mcp_type,
            image=image,
            environment=environment,
            port=0,  # Will be set below
            internal_port=internal_port,
        )
        
        # Allocate port
        port = self._allocate_port(mcp_type, temp_config.container_name)
        
        return ContainerConfig(
            customer_name=customer_name,
            mcp_type=mcp_type,
            image=image,
            environment=environment,
            port=port,
            internal_port=internal_port,
        )
    
    async def _start_container(self, config: ContainerConfig) -> ContainerStatus:
        """Start a single MCP container."""
        status = ContainerStatus(config=config, state=ContainerState.STARTING)
        
        try:
            # Check if container already exists
            try:
                existing = self.docker.containers.get(config.container_name)
                if existing.status == "running":
                    logger.info(f"Container {config.container_name} already running")
                    status.state = ContainerState.RUNNING
                    status.container_id = existing.id
                    status.started_at = time.time()
                    return status
                else:
                    # Remove stopped container
                    existing.remove(force=True)
            except NotFound:
                pass
            
            # Ensure network exists
            self._ensure_network()
            
            # Pull image if needed
            try:
                self.docker.images.get(config.image)
            except ImageNotFound:
                logger.info(f"Pulling image: {config.image}")
                self.docker.images.pull(config.image)
            
            # Build command based on MCP type
            command = None
            if config.mcp_type == MCPType.GRAFANA:
                command = ["--transport", "streamable-http", "--address", f"0.0.0.0:{config.internal_port}"]
            
            # Start container
            logger.info(
                f"Starting container {config.container_name} "
                f"(image={config.image}, port={config.port})"
            )
            
            container = self.docker.containers.run(
                config.image,
                command=command,
                name=config.container_name,
                detach=True,
                environment=config.environment,
                ports={f"{config.internal_port}/tcp": config.port},
                network=self._network_name,
                restart_policy={"Name": "unless-stopped"},
                labels={
                    "sm3.managed": "true",
                    "sm3.customer": config.customer_name,
                    "sm3.mcp_type": config.mcp_type.value,
                },
            )
            
            status.container_id = container.id
            status.started_at = time.time()
            status.state = ContainerState.RUNNING
            
            logger.info(f"Container {config.container_name} started (id={container.short_id})")
            
        except Exception as e:
            logger.error(f"Failed to start container {config.container_name}: {e}")
            status.state = ContainerState.ERROR
            status.error_message = str(e)
        
        return status
    
    async def _wait_for_healthy(
        self,
        status: ContainerStatus,
        timeout: Optional[int] = None,
    ) -> ContainerStatus:
        """Wait for container to become healthy."""
        if status.state == ContainerState.ERROR:
            return status
        
        timeout = timeout or self._health_timeout
        start_time = time.time()
        
        logger.info(f"Waiting for {status.config.container_name} to become healthy...")
        
        while time.time() - start_time < timeout:
            try:
                # Try to connect to the health endpoint
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    url = status.config.url
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status in (200, 405):  # 405 = Method Not Allowed (but endpoint exists)
                            status.state = ContainerState.HEALTHY
                            logger.info(f"Container {status.config.container_name} is healthy")
                            return status
            except Exception as e:
                logger.debug(f"Health check failed for {status.config.container_name}: {e}")
            
            await asyncio.sleep(self._health_interval)
        
        status.state = ContainerState.UNHEALTHY
        status.error_message = f"Health check timeout after {timeout}s"
        logger.warning(f"Container {status.config.container_name} failed health check")
        
        return status
    
    async def _stop_container(self, status: ContainerStatus) -> None:
        """Stop and remove a container."""
        if not status.container_id:
            return
        
        try:
            status.state = ContainerState.STOPPING
            container = self.docker.containers.get(status.container_id)
            
            logger.info(f"Stopping container {status.config.container_name}")
            container.stop(timeout=10)
            container.remove()
            
            self._release_port(status.config.container_name)
            status.state = ContainerState.STOPPED
            
            logger.info(f"Container {status.config.container_name} stopped and removed")
            
        except NotFound:
            status.state = ContainerState.NOT_FOUND
        except Exception as e:
            logger.error(f"Error stopping container {status.config.container_name}: {e}")
            status.state = ContainerState.ERROR
            status.error_message = str(e)
    
    async def _enforce_lru_limit(self) -> None:
        """Stop containers exceeding the warm limit (LRU eviction)."""
        while len(self._customers) > self._max_warm:
            # Get oldest (least recently used) customer
            oldest_name = next(iter(self._customers))
            oldest = self._customers.pop(oldest_name)
            
            logger.info(f"Evicting LRU customer containers: {oldest_name}")
            
            # Stop all containers for this customer
            for status in oldest.containers.values():
                await self._stop_container(status)
    
    async def start_customer_containers(
        self,
        customer_name: str,
        mcp_servers: List[Dict[str, Any]],
        wait_for_healthy: bool = True,
    ) -> CustomerContainers:
        """
        Start all MCP containers for a customer.
        
        Args:
            customer_name: Name of the customer
            mcp_servers: List of MCP server configs from mcp_servers.json
            wait_for_healthy: Whether to wait for health checks
            
        Returns:
            CustomerContainers with status of all containers
        """
        # Check if already running (move to end of LRU)
        if customer_name in self._customers:
            customer = self._customers.pop(customer_name)
            customer.update_access_time()
            self._customers[customer_name] = customer
            
            # Check if all still healthy
            if customer.all_healthy():
                logger.info(f"Customer {customer_name} containers already healthy")
                return customer
        
        # Create new customer containers
        customer = CustomerContainers(customer_name=customer_name)
        
        # Start containers in parallel
        start_tasks = []
        for server_config in mcp_servers:
            type_str = server_config.get("type", "")
            try:
                mcp_type = MCPType(type_str)
            except ValueError:
                logger.warning(f"Unknown MCP type: {type_str}")
                continue
            
            config = self._build_container_config(customer_name, mcp_type, server_config)
            start_tasks.append(self._start_container(config))
        
        # Wait for all containers to start
        statuses = await asyncio.gather(*start_tasks)
        
        for status in statuses:
            customer.containers[status.config.mcp_type] = status
        
        # Wait for health checks
        if wait_for_healthy:
            health_tasks = [
                self._wait_for_healthy(status)
                for status in customer.containers.values()
                if status.state == ContainerState.RUNNING
            ]
            await asyncio.gather(*health_tasks)
        
        # Add to LRU cache
        self._customers[customer_name] = customer
        
        # Enforce LRU limit
        await self._enforce_lru_limit()
        
        return customer
    
    async def stop_customer_containers(self, customer_name: str) -> None:
        """Stop all containers for a customer."""
        if customer_name not in self._customers:
            return
        
        customer = self._customers.pop(customer_name)
        
        for status in customer.containers.values():
            await self._stop_container(status)
    
    async def stop_all_containers(self) -> None:
        """Stop all managed containers."""
        for customer_name in list(self._customers.keys()):
            await self.stop_customer_containers(customer_name)
    
    def get_customer_status(self, customer_name: str) -> Optional[CustomerContainers]:
        """Get status of containers for a customer."""
        return self._customers.get(customer_name)
    
    def get_active_customers(self) -> List[str]:
        """Get list of customers with active containers."""
        return list(self._customers.keys())
    
    def get_container_urls(self, customer_name: str) -> Dict[str, str]:
        """Get MCP URLs for a customer's containers."""
        customer = self._customers.get(customer_name)
        if not customer:
            return {}
        
        return {
            mcp_type.value: status.config.url
            for mcp_type, status in customer.containers.items()
            if status.state == ContainerState.HEALTHY
        }
    
    def cleanup_orphaned_containers(self) -> int:
        """Find and remove orphaned SM3 containers."""
        removed = 0
        try:
            containers = self.docker.containers.list(
                all=True,
                filters={"label": "sm3.managed=true"}
            )
            
            managed_ids = {
                s.container_id
                for c in self._customers.values()
                for s in c.containers.values()
                if s.container_id
            }
            
            for container in containers:
                if container.id not in managed_ids:
                    logger.info(f"Removing orphaned container: {container.name}")
                    container.remove(force=True)
                    removed += 1
                    
        except Exception as e:
            logger.error(f"Error cleaning up orphaned containers: {e}")
        
        return removed


# Singleton accessor
def get_container_manager() -> MCPContainerManager:
    """Get the singleton container manager instance."""
    return MCPContainerManager()
