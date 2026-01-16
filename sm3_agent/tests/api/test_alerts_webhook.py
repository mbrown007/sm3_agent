"""
Tests for multi-customer alert webhook isolation.

CRITICAL: These tests verify customer data isolation to prevent
customer A from accessing customer B's alert data.
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.alerts import (
    get_webhook_state,
    _update_webhook_state,
    _get_analysis_dir,
)


@pytest.mark.customer_isolation
@pytest.mark.asyncio
async def test_webhook_state_customer_isolation():
    """Verify webhook state is isolated per customer."""
    # Update state for CustomerA
    _update_webhook_state("CustomerA", total_alerts_received=5, pending_analyses=2)
    
    # Update state for CustomerB
    _update_webhook_state("CustomerB", total_alerts_received=10, pending_analyses=1)
    
    # Verify CustomerA state
    state_a = get_webhook_state("CustomerA")
    assert state_a["total_alerts_received"] == 5
    assert state_a["pending_analyses"] == 2
    
    # Verify CustomerB state
    state_b = get_webhook_state("CustomerB")
    assert state_b["total_alerts_received"] == 10
    assert state_b["pending_analyses"] == 1
    
    # Verify CustomerC (non-existent) returns default state
    state_c = get_webhook_state("CustomerC")
    assert state_c["total_alerts_received"] == 0
    assert state_c["pending_analyses"] == 0


@pytest.mark.customer_isolation
@pytest.mark.asyncio
async def test_analysis_directory_customer_isolation(temp_dir):
    """Verify alert analyses are stored in customer-specific directories."""
    with patch("backend.api.alerts.Path", return_value=temp_dir / "alert-analyses"):
        # Get analysis directories for different customers
        dir_a = _get_analysis_dir("CustomerA")
        dir_b = _get_analysis_dir("CustomerB")
        
        # Verify directories are separate
        assert "CustomerA" in str(dir_a)
        assert "CustomerB" in str(dir_b)
        assert dir_a != dir_b
        
        # Create mock analysis files
        dir_a.mkdir(parents=True, exist_ok=True)
        dir_b.mkdir(parents=True, exist_ok=True)
        
        (dir_a / "analysis-1.json").write_text(json.dumps({"customer": "A"}))
        (dir_b / "analysis-2.json").write_text(json.dumps({"customer": "B"}))
        
        # Verify CustomerA cannot access CustomerB's files
        assert len(list(dir_a.glob("*.json"))) == 1
        assert len(list(dir_b.glob("*.json"))) == 1


@pytest.mark.customer_isolation
@pytest.mark.asyncio
async def test_concurrent_webhook_alerts(
    mock_mcp_server_manager,
    mock_container_manager,
    mock_agent_manager,
    sample_alert_payload
):
    """Test concurrent alerts from multiple customers don't interfere."""
    from backend.api.alerts import process_alertmanager_alert_customer
    
    with patch("backend.api.alerts.get_mcp_server_manager", return_value=mock_mcp_server_manager), \
         patch("backend.api.alerts.get_container_manager", return_value=mock_container_manager), \
         patch("backend.api.alerts.AgentManager", return_value=mock_agent_manager):
        
        # Configure mock for different customers
        def get_customer_side_effect(name):
            customer = MagicMock()
            customer.name = name
            customer.grafana_url = f"https://{name.lower()}.example.com"
            customer._raw_mcp_servers = []
            return customer
        
        mock_mcp_server_manager.get_customer.side_effect = get_customer_side_effect
        
        # Send alerts concurrently for different customers
        tasks = [
            process_alertmanager_alert_customer("CustomerA", sample_alert_payload),
            process_alertmanager_alert_customer("CustomerB", sample_alert_payload),
            process_alertmanager_alert_customer("CustomerC", sample_alert_payload),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify all processed without errors
        for result in results:
            assert not isinstance(result, Exception)
        
        # Verify each customer has their own state
        state_a = get_webhook_state("CustomerA")
        state_b = get_webhook_state("CustomerB")
        state_c = get_webhook_state("CustomerC")
        
        assert state_a["total_alerts_received"] >= 1
        assert state_b["total_alerts_received"] >= 1
        assert state_c["total_alerts_received"] >= 1


@pytest.mark.thread_safety
@pytest.mark.asyncio
async def test_webhook_state_thread_safety():
    """Verify webhook state updates are thread-safe."""
    import threading
    
    def update_counter(customer_name: str, iterations: int):
        """Increment counter multiple times."""
        for _ in range(iterations):
            state = get_webhook_state(customer_name)
            _update_webhook_state(
                customer_name,
                total_alerts_received=state["total_alerts_received"] + 1
            )
    
    # Run concurrent updates
    threads = []
    iterations = 100
    num_threads = 10
    
    for i in range(num_threads):
        thread = threading.Thread(
            target=update_counter,
            args=("ThreadTestCustomer", iterations)
        )
        threads.append(thread)
        thread.start()
    
    # Wait for all threads
    for thread in threads:
        thread.join()
    
    # Verify final count is correct (no lost updates)
    state = get_webhook_state("ThreadTestCustomer")
    assert state["total_alerts_received"] == iterations * num_threads


@pytest.mark.customer_isolation
def test_webhook_state_returns_copy():
    """Verify get_webhook_state returns a copy to prevent external mutation."""
    _update_webhook_state("MutationTest", total_alerts_received=10)
    
    # Get state
    state = get_webhook_state("MutationTest")
    original_value = state["total_alerts_received"]
    
    # Try to mutate the returned dict
    state["total_alerts_received"] = 999
    
    # Verify internal state unchanged
    state_again = get_webhook_state("MutationTest")
    assert state_again["total_alerts_received"] == original_value
    assert state_again["total_alerts_received"] != 999
