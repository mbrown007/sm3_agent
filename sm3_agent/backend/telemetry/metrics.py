"""
Prometheus metrics for monitoring agent performance and usage.
"""
from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST
from backend.utils.logger import get_logger

logger = get_logger(__name__)

# ============================================================================
# Chat Metrics
# ============================================================================

chat_requests_total = Counter(
    'agent_chat_requests_total',
    'Total number of chat requests',
    ['session_id', 'status']  # status: success, error
)

chat_duration_seconds = Histogram(
    'agent_chat_duration_seconds',
    'Chat request processing time in seconds',
    ['session_id'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
)

chat_streaming_requests_total = Counter(
    'agent_chat_streaming_requests_total',
    'Total number of streaming chat requests',
    ['session_id']
)

# ============================================================================
# Tool Usage Metrics
# ============================================================================

tool_invocations_total = Counter(
    'agent_tool_invocations_total',
    'Total tool invocations',
    ['tool_name', 'status']  # status: success, error, cache_hit
)

tool_duration_seconds = Histogram(
    'agent_tool_duration_seconds',
    'Tool execution time in seconds',
    ['tool_name'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0)
)

tool_cache_hits_total = Counter(
    'agent_tool_cache_hits_total',
    'Number of cache hits for tool results',
    ['tool_name']
)

tool_cache_misses_total = Counter(
    'agent_tool_cache_misses_total',
    'Number of cache misses for tool results',
    ['tool_name']
)

# ============================================================================
# LLM Metrics
# ============================================================================

llm_tokens_total = Counter(
    'agent_llm_tokens_total',
    'Total LLM tokens consumed',
    ['model', 'type']  # type: prompt, completion
)

llm_requests_total = Counter(
    'agent_llm_requests_total',
    'Total LLM API requests',
    ['model', 'status']
)

llm_duration_seconds = Histogram(
    'agent_llm_duration_seconds',
    'LLM request duration in seconds',
    ['model'],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0)
)

llm_cost_dollars = Counter(
    'agent_llm_cost_dollars',
    'Estimated LLM cost in dollars',
    ['model']
)

# ============================================================================
# Session Metrics
# ============================================================================

active_sessions = Gauge(
    'agent_active_sessions',
    'Number of active chat sessions'
)

sessions_total = Counter(
    'agent_sessions_total',
    'Total number of sessions created'
)

session_messages_total = Counter(
    'agent_session_messages_total',
    'Total messages per session',
    ['session_id']
)

# ============================================================================
# Cache Metrics
# ============================================================================

cache_size = Gauge(
    'agent_cache_size',
    'Current number of items in cache'
)

cache_hit_rate = Gauge(
    'agent_cache_hit_rate',
    'Cache hit rate (0-1)'
)

cache_evictions_total = Counter(
    'agent_cache_evictions_total',
    'Total number of cache evictions'
)

# ============================================================================
# Monitoring System Metrics
# ============================================================================

monitoring_targets_total = Gauge(
    'agent_monitoring_targets_total',
    'Total number of monitoring targets'
)

monitoring_targets_enabled = Gauge(
    'agent_monitoring_targets_enabled',
    'Number of enabled monitoring targets'
)

monitoring_checks_total = Counter(
    'agent_monitoring_checks_total',
    'Total monitoring checks performed',
    ['target_name', 'status']
)

monitoring_anomalies_detected = Counter(
    'agent_monitoring_anomalies_detected',
    'Number of anomalies detected',
    ['target_name', 'severity', 'method']
)

monitoring_alerts_total = Counter(
    'agent_monitoring_alerts_total',
    'Total alerts generated',
    ['target_name', 'severity']
)

monitoring_alerts_acknowledged = Counter(
    'agent_monitoring_alerts_acknowledged',
    'Total alerts acknowledged',
    ['target_name']
)

# ============================================================================
# System Info
# ============================================================================

agent_info = Info(
    'agent_info',
    'Agent version and configuration information'
)

# ============================================================================
# Error Metrics
# ============================================================================

errors_total = Counter(
    'agent_errors_total',
    'Total errors by type',
    ['error_type', 'component']
)

# ============================================================================
# Helper Functions
# ============================================================================

def update_cache_metrics(cache_stats: dict):
    """Update cache metrics from cache stats."""
    cache_size.set(cache_stats.get('size', 0))
    cache_hit_rate.set(cache_stats.get('hit_rate_percent', 0) / 100)
    # Evictions are cumulative, so we track the delta

def update_monitoring_metrics(status: dict):
    """Update monitoring system metrics."""
    monitoring_targets_total.set(status.get('targets_count', 0))
    monitoring_targets_enabled.set(status.get('enabled_targets', 0))

def set_agent_info(version: str, model: str, mcp_server: str):
    """Set agent information."""
    agent_info.info({
        'version': version,
        'model': model,
        'mcp_server': mcp_server
    })

def get_metrics():
    """Get metrics in Prometheus format."""
    return generate_latest()

def get_content_type():
    """Get Prometheus content type."""
    return CONTENT_TYPE_LATEST
