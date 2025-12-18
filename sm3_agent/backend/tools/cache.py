"""
Caching layer for MCP tool results.

Provides TTL-based caching to reduce redundant API calls and improve response times.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable, Dict, Optional
from functools import wraps

from backend.utils.logger import get_logger

logger = get_logger(__name__)


class CacheEntry:
    """Single cache entry with TTL."""

    def __init__(self, value: Any, ttl: int):
        self.value = value
        self.expires_at = time.time() + ttl
        self.created_at = time.time()

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at

    def age(self) -> float:
        """Get age of cache entry in seconds."""
        return time.time() - self.created_at


class ToolResultCache:
    """
    LRU cache with TTL for tool results.

    Caches results of expensive MCP operations like dashboard fetches,
    datasource lists, and alert rules.
    """

    # Default TTL values for different tool types (in seconds)
    DEFAULT_TTLS = {
        "get_dashboard_by_uid": 300,  # 5 minutes
        "get_dashboard_summary": 300,
        "list_datasources": 600,  # 10 minutes
        "get_datasource_by_uid": 600,
        "list_alert_rules": 180,  # 3 minutes
        "list_oncall_schedules": 300,
        "search_dashboards": 120,  # 2 minutes
        # Don't cache queries - they need fresh data
        "query_prometheus": 0,
        "query_loki_logs": 0,
    }

    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        """
        Initialize cache.

        Args:
            max_size: Maximum number of entries to cache
            default_ttl: Default TTL in seconds for entries
        """
        self.cache: Dict[str, CacheEntry] = {}
        self.max_size = max_size
        self.default_ttl = default_ttl

        # Statistics
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def _make_key(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Generate cache key from tool name and arguments.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments

        Returns:
            Hex string cache key
        """
        # Sort arguments to ensure consistent key generation
        args_str = json.dumps(arguments, sort_keys=True)
        key_str = f"{tool_name}:{args_str}"
        return hashlib.sha256(key_str.encode()).hexdigest()

    def _get_ttl(self, tool_name: str) -> int:
        """Get TTL for a specific tool."""
        return self.DEFAULT_TTLS.get(tool_name, self.default_ttl)

    def _should_cache(self, tool_name: str) -> bool:
        """Check if tool results should be cached."""
        ttl = self._get_ttl(tool_name)
        return ttl > 0

    def _evict_oldest(self):
        """Evict oldest cache entry."""
        if not self.cache:
            return

        oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k].created_at)
        del self.cache[oldest_key]
        self.evictions += 1
        logger.debug(f"Evicted cache entry: {oldest_key}")

    def _cleanup_expired(self):
        """Remove expired entries."""
        expired_keys = [k for k, v in self.cache.items() if v.is_expired()]
        for key in expired_keys:
            del self.cache[key]
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

    def get(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Any]:
        """
        Get cached result.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments

        Returns:
            Cached result or None if not found/expired
        """
        if not self._should_cache(tool_name):
            return None

        key = self._make_key(tool_name, arguments)
        entry = self.cache.get(key)

        if entry is None:
            self.misses += 1
            logger.debug(f"Cache miss: {tool_name}")
            return None

        if entry.is_expired():
            del self.cache[key]
            self.misses += 1
            logger.debug(f"Cache expired: {tool_name}")
            return None

        self.hits += 1
        logger.debug(f"Cache hit: {tool_name} (age: {entry.age():.1f}s)")
        return entry.value

    def set(self, tool_name: str, arguments: Dict[str, Any], value: Any):
        """
        Store result in cache.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            value: Result to cache
        """
        if not self._should_cache(tool_name):
            return

        # Cleanup expired entries periodically
        if len(self.cache) > self.max_size * 0.9:
            self._cleanup_expired()

        # Evict oldest if at capacity
        if len(self.cache) >= self.max_size:
            self._evict_oldest()

        key = self._make_key(tool_name, arguments)
        ttl = self._get_ttl(tool_name)
        self.cache[key] = CacheEntry(value, ttl)

        logger.debug(f"Cached: {tool_name} (TTL: {ttl}s)")

    def invalidate(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None):
        """
        Invalidate cache entries.

        Args:
            tool_name: Name of the tool
            arguments: Specific arguments to invalidate, or None for all
        """
        if arguments is not None:
            key = self._make_key(tool_name, arguments)
            if key in self.cache:
                del self.cache[key]
                logger.debug(f"Invalidated: {tool_name}")
        else:
            # Invalidate all entries for this tool
            keys_to_delete = [
                k for k in self.cache.keys()
                if k.startswith(hashlib.sha256(f"{tool_name}:".encode()).hexdigest()[:8])
            ]
            for key in keys_to_delete:
                del self.cache[key]
            logger.debug(f"Invalidated {len(keys_to_delete)} entries for {tool_name}")

    def clear(self):
        """Clear all cache entries."""
        count = len(self.cache)
        self.cache.clear()
        logger.info(f"Cleared {count} cache entries")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0

        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate_percent": round(hit_rate, 2),
            "total_requests": total_requests
        }


# Global cache instance
_cache_instance: Optional[ToolResultCache] = None


def get_cache() -> ToolResultCache:
    """Get or create global cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ToolResultCache()
        logger.info("Initialized tool result cache")
    return _cache_instance


def cached_tool(func: Callable) -> Callable:
    """
    Decorator to cache tool results.

    Usage:
        @cached_tool
        async def my_tool(tool_name: str, arguments: dict):
            return await expensive_operation()
    """
    @wraps(func)
    async def wrapper(tool_name: str, arguments: Dict[str, Any], *args, **kwargs):
        cache = get_cache()

        # Try to get from cache
        cached_result = cache.get(tool_name, arguments)
        if cached_result is not None:
            return cached_result

        # Execute function
        result = await func(tool_name, arguments, *args, **kwargs)

        # Store in cache
        cache.set(tool_name, arguments, result)

        return result

    return wrapper
