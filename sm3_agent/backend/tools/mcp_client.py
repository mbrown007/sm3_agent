from __future__ import annotations

from typing import Any, Dict, List

from modelcontextprotocol.client import Client
from modelcontextprotocol.client.streamable_http import streamablehttp_client

from backend.app.config import Settings
from backend.tools.cache import get_cache
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class MCPClient:
    """
    MCP client wrapper for Grafana MCP server with proper lifecycle management.

    Supports async context manager pattern for automatic cleanup.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = Client(app_name="grafana-mcp-chat")
        self._transport = None
        self._connection_attempts = 0
        self._max_retries = 3

    async def __aenter__(self) -> MCPClient:
        """Async context manager entry - establishes connection."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - ensures proper cleanup."""
        await self.disconnect()

    async def connect(self) -> None:
        """
        Establish a connection to the MCP server with retry logic.

        Raises:
            Exception: If connection fails after max retries
        """
        if self.client.connected:
            logger.debug("Already connected to MCP server")
            return

        while self._connection_attempts < self._max_retries:
            try:
                logger.info(
                    f"Connecting to MCP server (attempt {self._connection_attempts + 1}/{self._max_retries})",
                    extra={"url": self.settings.mcp_server_url}
                )

                self._transport = streamablehttp_client(url=self.settings.mcp_server_url)
                await self.client.connect(self._transport)

                logger.info("Successfully connected to MCP server", extra={"url": self.settings.mcp_server_url})
                self._connection_attempts = 0
                return

            except Exception as e:
                self._connection_attempts += 1
                logger.error(
                    f"Failed to connect to MCP server: {e}",
                    extra={
                        "url": self.settings.mcp_server_url,
                        "attempt": self._connection_attempts,
                        "max_retries": self._max_retries
                    }
                )

                if self._connection_attempts >= self._max_retries:
                    raise Exception(
                        f"Failed to connect to MCP server after {self._max_retries} attempts: {e}"
                    ) from e

    async def disconnect(self) -> None:
        """Gracefully disconnect from the MCP server."""
        try:
            if self.client.connected:
                # Note: MCP Client doesn't have explicit disconnect in current API
                # but we mark intent to disconnect for future compatibility
                logger.info("Disconnecting from MCP server")
                # Reset connection state
                self._transport = None
                self._connection_attempts = 0
        except Exception as e:
            logger.warning(f"Error during disconnect: {e}")

    async def ensure_connected(self) -> None:
        """Ensure connection is established, reconnect if needed."""
        if not self.client.connected:
            logger.warning("Connection lost, attempting to reconnect")
            await self.connect()

    async def invoke_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """
        Invoke an MCP tool by name with arguments (with caching).

        Args:
            name: Tool name to invoke
            arguments: Dictionary of arguments for the tool

        Returns:
            Tool execution result (may be from cache)

        Raises:
            Exception: If tool invocation fails
        """
        cache = get_cache()

        # Try to get from cache first
        cached_result = cache.get(name, arguments)
        if cached_result is not None:
            logger.info(f"Cache hit for tool: {name}")
            return cached_result

        try:
            await self.ensure_connected()

            logger.debug(f"Invoking tool: {name}", extra={"arguments": arguments})
            response = await self.client.call_tool(name=name, arguments=arguments)

            if response and hasattr(response, 'content'):
                result = response.content

                # Store in cache
                cache.set(name, arguments, result)

                return result
            else:
                logger.warning(f"Tool {name} returned no content")
                return {"error": f"No response from tool {name}"}

        except Exception as e:
            logger.error(
                f"Tool invocation failed: {e}",
                extra={"tool": name, "arguments": arguments}
            )
            raise Exception(f"Failed to invoke tool '{name}': {str(e)}") from e

    def invalidate_cache(self, tool_name: str, arguments: Dict[str, Any] = None):
        """
        Invalidate cache for a specific tool.

        Useful after write operations (update_dashboard, etc.)

        Args:
            tool_name: Name of the tool to invalidate
            arguments: Specific arguments to invalidate, or None for all
        """
        cache = get_cache()
        cache.invalidate(tool_name, arguments)
        logger.info(f"Invalidated cache for: {tool_name}")
