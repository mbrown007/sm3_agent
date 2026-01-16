# SM3 Agent Testing Guide

## Overview

This directory contains automated tests for the SM3 Agent application, with a focus on:
- **Multi-customer data isolation** (preventing customer A from accessing customer B's data)
- **Thread-safety** (concurrent webhook processing)
- **Knowledge base matching accuracy**
- **AI investigation correctness**

## Running Tests

### Install Test Dependencies

```bash
cd sm3_agent
pip install -r requirements-dev.txt
```

### Run All Tests

```bash
pytest
```

### Run Specific Test Categories

```bash
# Customer isolation tests only
pytest -m customer_isolation

# Thread safety tests
pytest -m thread_safety

# Unit tests only
pytest -m unit

# With coverage report
pytest --cov=backend --cov-report=html
```

### Run Specific Test Files

```bash
# Alert webhook tests
pytest tests/api/test_alerts_webhook.py

# KB matching tests
pytest tests/agents/test_kb_matching.py
```

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── api/
│   ├── test_alerts_webhook.py    # Critical: Customer isolation tests
│   └── test_chat_api.py          # Chat streaming tests (TODO)
├── agents/
│   ├── test_kb_matching.py       # Knowledge base matching
│   └── test_agent_manager.py     # AI investigation tests (TODO)
├── containers/
│   └── test_container_manager.py # Container management (TODO)
└── fixtures/
    └── kb/                   # Test knowledge base entries
```

## Critical Test Scenarios

### 1. Customer Isolation (CRITICAL - Data Security)
- Alerts sent to `/api/alerts/ingest/CustomerA` must not be accessible by CustomerB
- Analysis files stored in customer-specific directories
- Webhook state tracked separately per customer
- Concurrent alerts from multiple customers don't interfere

**Test:** `tests/api/test_alerts_webhook.py::test_webhook_state_customer_isolation`

### 2. Thread Safety (CRITICAL - Concurrent Processing)
- Webhook state dictionary uses thread locks
- Concurrent updates don't cause race conditions
- No lost increments in pending_analyses counter

**Test:** `tests/api/test_alerts_webhook.py::test_webhook_state_thread_safety`

### 3. Knowledge Base Matching (HIGH - Accuracy)
- Exact alert name matches score high
- Partial keyword matches work correctly
- Score threshold filters low-quality matches
- Empty KB directory handled gracefully

**Test:** `tests/agents/test_kb_matching.py`

## Test Markers

Tests are tagged with markers for selective execution:

- `@pytest.mark.unit` - Fast unit tests
- `@pytest.mark.integration` - Integration tests (require external services)
- `@pytest.mark.customer_isolation` - Customer data isolation tests
- `@pytest.mark.thread_safety` - Concurrent access tests

## Coverage Goals

- **Backend:** Target 80%+ coverage
- **Critical paths:** 100% coverage
  - Alert webhook ingestion
  - Customer switching
  - Knowledge base matching
  - Session memory isolation

## Adding New Tests

1. Create test file in appropriate directory
2. Import fixtures from `conftest.py`
3. Use descriptive test names: `test_<what>_<expected_behavior>`
4. Add appropriate markers
5. Document CRITICAL tests with comments

Example:

```python
@pytest.mark.customer_isolation
@pytest.mark.asyncio
async def test_customer_data_isolation(mock_mcp_server_manager):
    """Verify customer A cannot access customer B's data."""
    # Test implementation
```

## CI/CD Integration (TODO)

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: |
          pip install -r requirements-dev.txt
          pytest --cov=backend --cov-fail-under=80
```

## Known Limitations

- **No E2E tests yet** - Using mocked dependencies instead of Testcontainers
- **No frontend tests** - React component testing TODO
- **No authentication tests** - Auth layer to be added

## Security Testing Notes

### Multi-Tenancy Risks

The following areas require rigorous testing due to multi-customer architecture:

1. **URL-based customer routing** - `/api/alerts/ingest/{customer_name}`
   - No authentication required
   - Customer separation relies on path parameter only
   - **Risk:** Malicious actor could send alerts to wrong customer

2. **Container isolation** - MCP containers per customer
   - Containers share Docker network
   - **Risk:** Container escape could expose customer data

3. **Shared webhook state** - Thread locks protect `_customer_webhook_state`
   - Race conditions could corrupt counters
   - **Test:** `test_webhook_state_thread_safety` validates lock correctness
