"""
Grafana server configuration management.

Loads and manages multiple Grafana server configurations from a JSON file,
allowing dynamic server selection at runtime.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from backend.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GrafanaServer:
    """Represents a single Grafana server configuration."""
    name: str
    url: str
    description: str = ""
    
    def __post_init__(self):
        # Ensure URL ends with /mcp if it doesn't already
        if not self.url.endswith("/mcp"):
            if self.url.endswith("/"):
                self.url = self.url + "mcp"
            else:
                self.url = self.url + "/mcp"


@dataclass
class GrafanaServersConfig:
    """Configuration for all Grafana servers."""
    servers: List[GrafanaServer] = field(default_factory=list)
    default: str = ""
    
    def get_server_by_name(self, name: str) -> Optional[GrafanaServer]:
        """Get a server by its name."""
        for server in self.servers:
            if server.name == name:
                return server
        return None
    
    def get_default_server(self) -> Optional[GrafanaServer]:
        """Get the default server."""
        if self.default:
            return self.get_server_by_name(self.default)
        if self.servers:
            return self.servers[0]
        return None
    
    def get_server_names(self) -> List[str]:
        """Get list of all server names for dropdown."""
        return [server.name for server in self.servers]
    
    def get_server_choices(self) -> Dict[str, str]:
        """Get server choices as name -> description for UI."""
        return {
            server.name: f"{server.name} - {server.description}" if server.description else server.name
            for server in self.servers
        }


class GrafanaServerManager:
    """Manages loading and accessing Grafana server configurations."""
    
    _instance: Optional["GrafanaServerManager"] = None
    _config: Optional[GrafanaServersConfig] = None
    
    def __new__(cls) -> "GrafanaServerManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._config is None:
            self.reload()
    
    def reload(self) -> None:
        """Reload configuration from disk."""
        self._config = self._load_config()
    
    def _load_config(self) -> GrafanaServersConfig:
        """Load Grafana servers configuration from JSON file."""
        # Look for config file in multiple locations
        config_paths = [
            Path(__file__).parent.parent.parent / "grafana_servers.json",  # sm3_agent/grafana_servers.json
            Path.cwd() / "grafana_servers.json",  # Current working directory
            Path.cwd() / "sm3_agent" / "grafana_servers.json",  # Subdirectory
        ]
        
        config_file = None
        for path in config_paths:
            if path.exists():
                config_file = path
                break
        
        if not config_file:
            logger.warning(
                "No grafana_servers.json found, using default configuration. "
                f"Searched: {[str(p) for p in config_paths]}"
            )
            return self._default_config()
        
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            servers = []
            for server_data in data.get("servers", []):
                servers.append(GrafanaServer(
                    name=server_data.get("name", "Unknown"),
                    url=server_data.get("url", ""),
                    description=server_data.get("description", "")
                ))
            
            config = GrafanaServersConfig(
                servers=servers,
                default=data.get("default", "")
            )
            
            logger.info(
                f"Loaded {len(servers)} Grafana server(s) from {config_file}",
                extra={"servers": [s.name for s in servers]}
            )
            
            return config
            
        except Exception as e:
            logger.error(f"Failed to load grafana_servers.json: {e}")
            return self._default_config()
    
    def _default_config(self) -> GrafanaServersConfig:
        """Return default configuration when no file is found."""
        return GrafanaServersConfig(
            servers=[
                GrafanaServer(
                    name="Local",
                    url="http://localhost:3001/mcp",
                    description="Local development Grafana"
                )
            ],
            default="Local"
        )
    
    @property
    def config(self) -> GrafanaServersConfig:
        """Get the current configuration."""
        if self._config is None:
            self.reload()
        return self._config
    
    def get_server(self, name: str) -> Optional[GrafanaServer]:
        """Get a server by name."""
        return self.config.get_server_by_name(name)
    
    def get_default(self) -> Optional[GrafanaServer]:
        """Get the default server."""
        return self.config.get_default_server()
    
    def get_server_names(self) -> List[str]:
        """Get list of server names."""
        return self.config.get_server_names()
    
    def get_server_url(self, name: str) -> Optional[str]:
        """Get URL for a server by name."""
        server = self.get_server(name)
        return server.url if server else None


def get_grafana_server_manager() -> GrafanaServerManager:
    """Get the singleton GrafanaServerManager instance."""
    return GrafanaServerManager()
