"""
Suggestion engine for follow-up questions.

Provides context-aware suggestions to guide users through investigations.
"""
from __future__ import annotations

from typing import Any, Dict, List

from backend.utils.logger import get_logger

logger = get_logger(__name__)


class SuggestionEngine:
    """
    Generates suggested follow-up questions based on tool usage and results.
    """

    # Pattern-based suggestions for common tools
    TOOL_SUGGESTIONS = {
        "list_datasources": [
            "Show me metrics from {datasource_name}",
            "What dashboards use {datasource_name}?",
            "Query recent data from {datasource_name}"
        ],
        "search_dashboards": [
            "Get summary of dashboard '{dashboard_title}'",
            "Show me the panels in '{dashboard_title}'",
            "What queries are in '{dashboard_title}'?"
        ],
        "get_dashboard_by_uid": [
            "Show me recent metrics from this dashboard",
            "What alerts are configured for this dashboard?",
            "Export this dashboard configuration"
        ],
        "get_dashboard_summary": [
            "Show me the full dashboard details",
            "Get panel queries from this dashboard",
            "What datasources does this dashboard use?"
        ],
        "query_prometheus": [
            "Show me the query in a graph",
            "What's the average value over the last hour?",
            "Are there any anomalies in this metric?"
        ],
        "query_loki_logs": [
            "Parse these logs for errors",
            "Show me the most common log patterns",
            "What happened around {timestamp}?"
        ],
        "list_alert_rules": [
            "Show me firing alerts",
            "What alerts are configured for {service}?",
            "When was this alert last triggered?"
        ],
        "list_oncall_schedules": [
            "Who is currently on-call?",
            "Show me this week's on-call schedule",
            "When is my next on-call shift?"
        ],
        "get_datasource_by_uid": [
            "Query this datasource",
            "What dashboards use this datasource?",
            "Test connectivity to this datasource"
        ]
    }

    # Context-based suggestions when certain patterns are detected
    CONTEXT_SUGGESTIONS = {
        "high_error_rate": [
            "Show me error logs from the last hour",
            "What changed recently in the deployment?",
            "Are other services affected?"
        ],
        "slow_response": [
            "Show me database query performance",
            "Check for high CPU or memory usage",
            "What's the p95 latency trend?"
        ],
        "alert_firing": [
            "Show me related logs",
            "What's the historical trend for this metric?",
            "Who is on-call right now?"
        ],
        "no_data": [
            "Check if the datasource is healthy",
            "When did we last receive data?",
            "Are there any scrape errors?"
        ]
    }

    def __init__(self):
        self.last_tool_used = None
        self.last_result = None

    def generate_suggestions(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        message: str
    ) -> List[str]:
        """
        Generate follow-up question suggestions.

        Args:
            tool_name: Name of the tool that was used
            tool_args: Arguments passed to the tool
            result: Result from the tool
            message: User's original message

        Returns:
            List of suggested follow-up questions
        """
        suggestions = []

        # Get tool-specific suggestions
        tool_suggestions = self._get_tool_suggestions(tool_name, tool_args, result)
        suggestions.extend(tool_suggestions)

        # Get context-based suggestions
        context_suggestions = self._get_context_suggestions(message, result)
        suggestions.extend(context_suggestions)

        # Get general investigation suggestions
        if not suggestions:
            suggestions = self._get_general_suggestions()

        # Deduplicate and limit to 3-5 suggestions
        suggestions = list(dict.fromkeys(suggestions))[:5]

        logger.debug(f"Generated {len(suggestions)} suggestions for {tool_name}")
        return suggestions

    def _get_tool_suggestions(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any
    ) -> List[str]:
        """Get suggestions based on the tool that was used."""
        suggestions = []

        # Get base suggestions for this tool
        base_suggestions = self.TOOL_SUGGESTIONS.get(tool_name, [])

        # Fill in placeholders with actual values from args/result
        for suggestion in base_suggestions:
            filled_suggestion = self._fill_placeholders(suggestion, tool_args, result)
            if filled_suggestion:
                suggestions.append(filled_suggestion)

        return suggestions

    def _fill_placeholders(
        self,
        suggestion: str,
        tool_args: Dict[str, Any],
        result: Any
    ) -> str:
        """Fill placeholders in suggestion templates."""
        # Try to extract relevant values
        replacements = {}

        # From tool arguments
        if "datasource" in tool_args:
            replacements["datasource_name"] = tool_args["datasource"]
        if "uid" in tool_args:
            replacements["dashboard_uid"] = tool_args["uid"]

        # From results (handle different result formats)
        if isinstance(result, list) and result:
            first_item = result[0]
            if isinstance(first_item, dict):
                if "name" in first_item:
                    replacements["datasource_name"] = first_item["name"]
                if "title" in first_item:
                    replacements["dashboard_title"] = first_item["title"]
                if "uid" in first_item:
                    replacements["dashboard_uid"] = first_item["uid"]

        elif isinstance(result, dict):
            if "title" in result:
                replacements["dashboard_title"] = result["title"]
            if "name" in result:
                replacements["datasource_name"] = result["name"]

        # Replace placeholders
        filled = suggestion
        for key, value in replacements.items():
            filled = filled.replace(f"{{{key}}}", str(value))

        # Only return if all placeholders were filled
        if "{" not in filled and "}" not in filled:
            return filled

        return ""

    def _get_context_suggestions(self, message: str, result: Any) -> List[str]:
        """Get suggestions based on message context and results."""
        suggestions = []
        message_lower = message.lower()

        # Detect context from message
        if any(word in message_lower for word in ["error", "errors", "failing", "failed"]):
            suggestions.extend(self.CONTEXT_SUGGESTIONS["high_error_rate"])

        if any(word in message_lower for word in ["slow", "latency", "timeout", "performance"]):
            suggestions.extend(self.CONTEXT_SUGGESTIONS["slow_response"])

        if any(word in message_lower for word in ["alert", "alerts", "alerting", "firing"]):
            suggestions.extend(self.CONTEXT_SUGGESTIONS["alert_firing"])

        # Detect context from results
        if isinstance(result, list) and len(result) == 0:
            suggestions.extend(self.CONTEXT_SUGGESTIONS["no_data"])

        return suggestions[:3]  # Limit context suggestions

    def _get_general_suggestions(self) -> List[str]:
        """Get general investigation suggestions."""
        return [
            "Show me active alerts",
            "What's the current error rate?",
            "List all datasources",
            "Search for dashboards",
            "Who is on-call now?"
        ]


# Global singleton
_suggestion_engine: SuggestionEngine | None = None


def get_suggestion_engine() -> SuggestionEngine:
    """Get or create global suggestion engine."""
    global _suggestion_engine
    if _suggestion_engine is None:
        _suggestion_engine = SuggestionEngine()
    return _suggestion_engine
