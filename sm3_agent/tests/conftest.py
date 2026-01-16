"""
Pytest configuration and shared fixtures.
"""
import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Dict, Generator
from unittest.mock import MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

# Set test environment variables before importing app
os.environ["TESTING"] = "true"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["MCP_SERVER_URL"] = "http://test-mcp:8888/mcp"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_mcp_server_manager():
    """Mock MCP server manager."""
    manager = MagicMock()
    
    # Mock customer
    mock_customer = MagicMock()
    mock_customer.name = "TestCustomer"
    mock_customer.grafana_url = "https://test-grafana.example.com"
    mock_customer._raw_mcp_servers = [
        {
            "name": "grafana",
            "container_name": "mcp-grafana-testcustomer",
            "image": "mcp-grafana:latest",
            "env": {"GRAFANA_URL": "https://test-grafana.example.com"}
        }
    ]
    
    manager.get_customer.return_value = mock_customer
    manager.list_customers.return_value = [
        {"name": "TestCustomer"},
        {"name": "AnotherCustomer"}
    ]
    
    return manager


@pytest.fixture
def mock_container_manager():
    """Mock container manager."""
    manager = AsyncMock()
    
    # Mock customer containers
    mock_containers = MagicMock()
    mock_containers.all_healthy.return_value = True
    mock_containers.get_mcp_urls.return_value = {
        "grafana": "http://test-mcp-grafana:8888/mcp"
    }
    
    manager.start_customer_containers = AsyncMock(return_value=mock_containers)
    manager._customers = {"TestCustomer": mock_containers}
    
    return manager


@pytest.fixture
def mock_agent_manager():
    """Mock agent manager."""
    agent = AsyncMock()
    
    # Mock investigation response
    agent.investigate_alert_with_runbooks = AsyncMock(return_value={
        "summary": "Test investigation summary",
        "root_cause_hypothesis": "Test root cause",
        "impact_assessment": "Test impact",
        "recommended_actions": ["Action 1", "Action 2"],
        "related_evidence": ["Evidence 1"],
        "confidence": 0.85
    })
    
    return agent


@pytest.fixture
def sample_alert_payload() -> Dict:
    """Sample AlertManager webhook payload."""
    return {
        "receiver": "webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighErrorRate",
                    "severity": "critical",
                    "service": "api"
                },
                "annotations": {
                    "summary": "Error rate above threshold",
                    "description": "API error rate is 15% (threshold: 5%)"
                },
                "startsAt": "2026-01-16T10:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "https://prometheus.example.com/graph?..."
            }
        ],
        "groupLabels": {"alertname": "HighErrorRate"},
        "commonLabels": {"alertname": "HighErrorRate", "severity": "critical"},
        "commonAnnotations": {"summary": "Error rate above threshold"},
        "externalURL": "https://alertmanager.example.com",
        "version": "4",
        "groupKey": "{}:{alertname=\"HighErrorRate\"}"
    }


@pytest.fixture
def sample_kb_entry() -> str:
    """Sample knowledge base entry content."""
    return """# High Error Rate Investigation

## Symptoms
- API error rate exceeds 5%
- Increased 5xx responses
- Database connection timeouts

## Root Cause
- Database connection pool exhausted
- Slow queries causing backlog

## Resolution Steps
1. Check database connection pool metrics
2. Identify slow queries in database logs
3. Optimize queries or increase pool size
4. Monitor error rate recovery

## Related Alerts
- DatabaseConnectionPoolExhausted
- SlowQueryDetected
"""


@pytest.fixture(autouse=True)
def reset_webhook_state():
    """Reset webhook state between tests."""
    from backend.api import alerts
    alerts._customer_webhook_state.clear()
    yield
    alerts._customer_webhook_state.clear()
