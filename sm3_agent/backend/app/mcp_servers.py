"""
MCP server configuration management.

Loads and manages multiple MCP server configurations per customer from a JSON file,
allowing dynamic customer selection at runtime with multiple MCP server types
(Grafana, AlertManager, etc.) per customer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MCPServer:
    """Represents a single MCP server configuration."""
    type: str  # "grafana", "alertmanager", "genesys", "ssh", etc.
    url: str = ""  # URL is now dynamically assigned by container manager
    config: Dict = field(default_factory=dict)  # Type-specific config (credentials, endpoints)
    
    def __post_init__(self):
        # Validate type
        valid_types = {"grafana", "alertmanager", "genesys", "ssh", "linux"}
        if self.type not in valid_types:
            logger.warning(f"Unknown MCP server type: {self.type}")
        # Ensure config is a dict
        if self.config is None:
            self.config = {}


@dataclass
class ContainerSettings:
    """Settings for dynamic container management."""
    max_warm_containers: int = 3
    health_check_timeout_seconds: int = 30
    health_check_interval_seconds: int = 2
    container_startup_timeout_seconds: int = 60
    idle_timeout_seconds: int = 1800  # 30 minutes default
    network_name: str = "sm3-mcp-network"
    port_ranges: Dict[str, Dict[str, int]] = field(default_factory=dict)
    images: Dict[str, str] = field(default_factory=dict)


@dataclass
class Customer:
    """Represents a customer with one or more MCP servers."""
    name: str
    description: str = ""
    host: str = ""  # The actual monitoring host (e.g., maas-ng-vattenfall.services.sabio.co.uk)
    has_genesys: bool = False  # Whether this customer has Genesys Cloud integration
    mcp_servers: List[MCPServer] = field(default_factory=list)
    # Raw server configs for container manager
    _raw_mcp_servers: List[Dict] = field(default_factory=list)
    
    def get_servers_by_type(self, server_type: str) -> List[MCPServer]:
        """Get all MCP servers of a specific type for this customer."""
        return [s for s in self.mcp_servers if s.type == server_type]
    
    def get_server_by_type(self, server_type: str) -> Optional[MCPServer]:
        """Get the first MCP server of a specific type for this customer."""
        servers = self.get_servers_by_type(server_type)
        return servers[0] if servers else None
    
    def get_server_types(self) -> List[str]:
        """Get list of all server types available for this customer."""
        return list(set(s.type for s in self.mcp_servers))


@dataclass
class MCPServersConfig:
    """Configuration for all customers and their MCP servers."""
    customers: List[Customer] = field(default_factory=list)
    default: str = ""
    container_settings: Optional[ContainerSettings] = None
    
    def get_customer_by_name(self, name: str) -> Optional[Customer]:
        """Get a customer by their name."""
        for customer in self.customers:
            if customer.name == name:
                return customer
        return None
    
    def get_default_customer(self) -> Optional[Customer]:
        """Get the default customer."""
        if self.default:
            return self.get_customer_by_name(self.default)
        if self.customers:
            return self.customers[0]
        return None
    
    def get_customer_names(self) -> List[str]:
        """Get list of all customer names for dropdown."""
        return [customer.name for customer in self.customers]
    
    def get_customer_choices(self) -> Dict[str, str]:
        """Get customer choices as name -> description for UI."""
        return {
            customer.name: f"{customer.name} - {customer.description}" if customer.description else customer.name
            for customer in self.customers
        }
    
    def get_genesys_customers(self) -> List[Customer]:
        """Get all customers that have Genesys Cloud integration."""
        return [c for c in self.customers if c.has_genesys]


class MCPServerManager:
    """Manages loading and accessing MCP server configurations per customer."""
    
    _instance: Optional["MCPServerManager"] = None
    _config: Optional[MCPServersConfig] = None
    
    def __new__(cls) -> "MCPServerManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._config is None:
            self.reload()
    
    def reload(self) -> None:
        """Reload configuration from disk."""
        self._config = self._load_config()
    
    def _load_config(self) -> MCPServersConfig:
        """Load MCP servers configuration from JSON file."""
        # Look for config file in multiple locations
        config_paths = [
            Path(__file__).parent.parent.parent / "mcp_servers.json",  # sm3_agent/mcp_servers.json
            Path.cwd() / "mcp_servers.json",  # Current working directory
            Path.cwd() / "sm3_agent" / "mcp_servers.json",  # Subdirectory
            # Fallback to old grafana_servers.json for backwards compatibility
            Path(__file__).parent.parent.parent / "grafana_servers.json",
        ]
        
        config_file = None
        for path in config_paths:
            if path.exists():
                config_file = path
                break
        
        if not config_file:
            logger.warning(
                "No mcp_servers.json found, using default configuration. "
                f"Searched: {[str(p) for p in config_paths]}"
            )
            return self._default_config()
        
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Check if this is the new customer-based format or old server-based format
            if "customers" in data:
                return self._parse_new_format(data, config_file)
            elif "servers" in data:
                return self._parse_legacy_format(data, config_file)
            else:
                logger.error(f"Unknown config format in {config_file}")
                return self._default_config()
            
        except Exception as e:
            logger.error(f"Failed to load mcp_servers.json: {e}")
            return self._default_config()
    
    def _parse_new_format(self, data: dict, config_file: Path) -> MCPServersConfig:
        """Parse the new customer-based config format with dynamic containers."""
        customers = []
        raw_servers_list = data.get("customers", [])
        
        for customer_data in raw_servers_list:
            mcp_servers = []
            raw_mcp_servers = customer_data.get("mcp_servers", [])
            
            for server_data in raw_mcp_servers:
                mcp_servers.append(MCPServer(
                    type=server_data.get("type", "grafana"),
                    url=server_data.get("url", ""),  # URL may be empty for dynamic containers
                    config=server_data.get("config", {})
                ))
            
            customers.append(Customer(
                name=customer_data.get("name", "Unknown"),
                description=customer_data.get("description", ""),
                host=customer_data.get("host", ""),
                has_genesys=customer_data.get("has_genesys", False),
                mcp_servers=mcp_servers,
                _raw_mcp_servers=raw_mcp_servers
            ))
        
        # Parse container settings if present
        container_settings = None
        if "container_settings" in data:
            cs = data["container_settings"]
            container_settings = ContainerSettings(
                max_warm_containers=cs.get("max_warm_containers", 3),
                health_check_timeout_seconds=cs.get("health_check_timeout_seconds", 30),
                health_check_interval_seconds=cs.get("health_check_interval_seconds", 2),
                container_startup_timeout_seconds=cs.get("container_startup_timeout_seconds", 60),
                idle_timeout_seconds=cs.get("idle_timeout_seconds", 1800),
                network_name=cs.get("network_name", "sm3-mcp-network"),
                port_ranges=cs.get("port_ranges", {}),
                images=cs.get("images", {})
            )
        
        config = MCPServersConfig(
            customers=customers,
            default=data.get("default", ""),
            container_settings=container_settings
        )
        
        total_servers = sum(len(c.mcp_servers) for c in customers)
        genesys_count = len([c for c in customers if c.has_genesys])
        logger.info(
            f"Loaded {len(customers)} customer(s) with {total_servers} MCP server(s) from {config_file}",
            extra={
                "customers": [c.name for c in customers],
                "genesys_customers": genesys_count,
                "has_container_settings": container_settings is not None
            }
        )
        
        return config
    
    def _parse_legacy_format(self, data: dict, config_file: Path) -> MCPServersConfig:
        """Parse the legacy grafana_servers.json format for backwards compatibility."""
        logger.info(f"Loading legacy format from {config_file}, consider migrating to mcp_servers.json")
        
        customers = []
        for server_data in data.get("servers", []):
            # Convert each server to a customer with a single Grafana MCP server
            customers.append(Customer(
                name=server_data.get("name", "Unknown"),
                description=server_data.get("description", ""),
                host=server_data.get("description", ""),  # Use description as host for legacy
                mcp_servers=[
                    MCPServer(
                        type="grafana",
                        url=server_data.get("url", "")
                    )
                ]
            ))
        
        config = MCPServersConfig(
            customers=customers,
            default=data.get("default", "")
        )
        
        logger.info(
            f"Loaded {len(customers)} customer(s) from legacy config {config_file}",
            extra={"customers": [c.name for c in customers]}
        )
        
        return config
    
    def _default_config(self) -> MCPServersConfig:
        """Return default configuration when no file is found."""
        return MCPServersConfig(
            customers=[
                Customer(
                    name="Local Dev",
                    description="Local development environment",
                    host="localhost",
                    mcp_servers=[
                        MCPServer(type="grafana", url="http://localhost:3001/mcp"),
                        MCPServer(type="alertmanager", url="http://localhost:9101/sse")
                    ]
                )
            ],
            default="Local Dev"
        )
    
    @property
    def config(self) -> MCPServersConfig:
        """Get the current configuration."""
        if self._config is None:
            self.reload()
        return self._config
    
    def get_customer(self, name: str) -> Optional[Customer]:
        """Get a customer by name."""
        return self.config.get_customer_by_name(name)
    
    def get_default(self) -> Optional[Customer]:
        """Get the default customer."""
        return self.config.get_default_customer()
    
    def get_customer_names(self) -> List[str]:
        """Get list of customer names."""
        return self.config.get_customer_names()
    
    def get_customer_servers(self, name: str) -> List[MCPServer]:
        """Get all MCP servers for a customer by name."""
        customer = self.get_customer(name)
        return customer.mcp_servers if customer else []
    
    # Backwards compatibility methods for grafana-only workflows
    def get_server(self, name: str) -> Optional[MCPServer]:
        """Get the Grafana server for a customer (backwards compatibility)."""
        customer = self.get_customer(name)
        return customer.get_server_by_type("grafana") if customer else None
    
    def get_server_names(self) -> List[str]:
        """Alias for get_customer_names (backwards compatibility)."""
        return self.get_customer_names()
    
    def get_server_url(self, name: str) -> Optional[str]:
        """Get Grafana URL for a customer by name (backwards compatibility)."""
        server = self.get_server(name)
        return server.url if server else None


def get_mcp_server_manager() -> MCPServerManager:
    """Get the singleton MCPServerManager instance."""
    return MCPServerManager()


# Backwards compatibility alias
def get_grafana_server_manager() -> MCPServerManager:
    """Alias for get_mcp_server_manager (backwards compatibility)."""
    return get_mcp_server_manager()
