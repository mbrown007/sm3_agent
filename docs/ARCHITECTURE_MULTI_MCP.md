# Multi-MCP Architecture for SM3 Agent

## Current State

The application currently supports:
- **Per-customer MCP servers**: Each customer can have multiple MCP servers (Grafana, AlertManager)
- **Customer dropdown**: Frontend allows switching between customers
- **Dynamic tool loading**: Agent rebuilds tools when switching customers
- **Single Docker MCP server**: Currently only runs one Grafana MCP server in Docker

### Current Files
```
grafana_servers.json     # Legacy format (Grafana-only, still supported)
sm3_agent/mcp_servers.json  # New format (multi-MCP per customer)
docker-compose.dev.yml   # Single MCP server config
```

## Problem Statement

1. **Genesys Cloud Integration**: Some customers have Genesys Cloud, some don't
2. **Dynamic Tool Availability**: Tools should change based on selected customer
3. **Efficient Docker Management**: Need to run multiple MCP servers efficiently
4. **Scalability**: Easy to add/remove customers and MCP types

## Proposed Architecture

### Option A: Dedicated MCP Containers Per Type (Recommended)

Run one container per MCP **type** that can serve multiple customers:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SM3 Agent Application                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Frontend (React)          │  Backend (FastAPI)                              │
│  - Customer dropdown       │  - Agent Manager                                │
│  - Shows available tools   │  - MCP Tool Builder                             │
│  - Chat interface          │  - Dynamic MCP connection                       │
└────────────────────────────┴────────────────────────────────────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
                    ▼                   ▼                   ▼
        ┌───────────────────┐ ┌─────────────────┐ ┌─────────────────┐
        │  Grafana MCP      │ │ AlertManager MCP│ │ Genesys Cloud   │
        │  Proxy Service    │ │ Proxy Service   │ │ MCP Service     │
        │  Port: 8001       │ │ Port: 8002      │ │ Port: 8003      │
        │                   │ │                 │ │                 │
        │  Environment:     │ │ Environment:    │ │ Environment:    │
        │  - Credentials    │ │ - Credentials   │ │ - Credentials   │
        │    per customer   │ │   per customer  │ │   per customer  │
        └───────────────────┘ └─────────────────┘ └─────────────────┘
                │                     │                   │
        ┌───────┴───────┐     ┌───────┴───────┐   ┌───────┴───────┐
        │ External      │     │ External      │   │ Genesys Cloud │
        │ Grafana       │     │ AlertManager  │   │ API           │
        │ Instances     │     │ Instances     │   │ (per customer)│
        └───────────────┘     └───────────────┘   └───────────────┘
```

**Pros:**
- Fewer containers (one per MCP type)
- Easier to manage/update
- Backend handles customer credential switching

**Cons:**
- Need to implement credential switching in backend
- Slightly more complex backend logic

### Option B: MCP Containers Per Customer-Type Combination

Run dedicated containers for each customer's MCP servers:

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                        Docker Compose (MCP Services)                           │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐             │
│  │ vattenfall-      │  │ vattenfall-      │  │ vattenfall-      │             │
│  │ grafana:3101     │  │ alertmgr:9201    │  │ genesys:9301     │             │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘             │
│                                                                                │
│  ┌──────────────────┐  ┌──────────────────┐                                   │
│  │ segurcaixa-      │  │ segurcaixa-      │  (No Genesys)                     │
│  │ grafana:3102     │  │ alertmgr:9202    │                                   │
│  └──────────────────┘  └──────────────────┘                                   │
│                                                                                │
│  ... more customers ...                                                        │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Pros:**
- Simpler per-container config (one customer, one credential set)
- Clear isolation between customers
- Can start/stop specific customer MCPs

**Cons:**
- Many containers (customers × MCP types)
- Higher resource usage
- Complex docker-compose file

### Option C: Hybrid - On-Demand Container Spawning

Backend spawns MCP containers on-demand when customer is selected:

**Pros:**
- Minimal resource usage
- Dynamic scaling

**Cons:**
- Cold start latency
- Complex orchestration
- Need container management in backend

## Recommended Approach: Option B with Smart Generation

### Why Option B?
1. **Simplicity**: Each container has single purpose
2. **Isolation**: Customer credentials stay in container
3. **Debugging**: Easy to restart/debug specific customer's MCP
4. **Selective Running**: Only start containers for active customers

### Implementation Plan

#### Phase 1: Configuration Restructure

Update `mcp_servers.json` to include all MCP types with credentials:

```json
{
  "customers": [
    {
      "name": "Vattenfall DE",
      "description": "maas-1203.mon.sabio.cloud",
      "host": "maas-1203.mon.sabio.cloud",
      "mcp_servers": [
        {
          "type": "grafana",
          "url": "http://mcp-grafana-vattenfall:8888/mcp",
          "config": {
            "grafana_url": "https://maas-1203.mon.sabio.cloud",
            "token_env": "GRAFANA_TOKEN_VATTENFALL"
          }
        },
        {
          "type": "alertmanager",
          "url": "http://mcp-alertmanager-vattenfall:8888/sse",
          "config": {
            "alertmanager_url": "http://maas-1203.mon.sabio.cloud:9093"
          }
        },
        {
          "type": "genesys",
          "url": "http://mcp-genesys-vattenfall:8888/sse",
          "config": {
            "region": "mypurecloud.de",
            "oauth_client_id_env": "GENESYS_CLIENT_ID_VATTENFALL",
            "oauth_client_secret_env": "GENESYS_CLIENT_SECRET_VATTENFALL"
          }
        }
      ]
    },
    {
      "name": "Segurcaixa",
      "description": "maas-1171.mon.sabio.cloud",
      "host": "maas-1171.mon.sabio.cloud",
      "mcp_servers": [
        {
          "type": "grafana",
          "url": "http://mcp-grafana-segurcaixa:8888/mcp"
        },
        {
          "type": "alertmanager",
          "url": "http://mcp-alertmanager-segurcaixa:8888/sse"
        }
        // No genesys - customer doesn't have it
      ]
    }
  ]
}
```

#### Phase 2: Docker Compose Generator

Create a script to generate `docker-compose.mcps.yml` from config:

```python
# scripts/generate_mcp_compose.py
# Reads mcp_servers.json and generates docker-compose with all MCP containers
```

#### Phase 3: Frontend Enhancement

Update frontend to show available tools for selected customer:

```tsx
// When customer changes:
// 1. Call /api/customers/switch
// 2. Response includes: { mcp_types: ["grafana", "alertmanager", "genesys"], tools: [...] }
// 3. UI shows which integrations are available
```

#### Phase 4: Agent Enhancement

Agent dynamically loads only tools from available MCP servers:

```python
async def switch_customer(self, customer_name: str) -> CustomerSwitchResult:
    customer = server_manager.get_customer(customer_name)
    
    # Connect to each available MCP server
    tools = []
    connected_types = []
    for server in customer.mcp_servers:
        try:
            server_tools = await connect_mcp_server(server)
            tools.extend(server_tools)
            connected_types.append(server.type)
        except ConnectionError:
            logger.warning(f"MCP server {server.type} not available for {customer_name}")
    
    return CustomerSwitchResult(
        customer=customer_name,
        mcp_types=connected_types,
        tool_count=len(tools)
    )
```

## Docker Management Strategy

### Development: All-in-One

```bash
# Start all MCP services for development
docker-compose -f docker-compose.mcps.yml up -d

# Or specific customers
docker-compose -f docker-compose.mcps.yml up -d \
  mcp-grafana-vattenfall mcp-alertmanager-vattenfall mcp-genesys-vattenfall
```

### Production: Kubernetes/Docker Swarm

For production, consider:
1. **Kubernetes**: Deploy MCPs as StatefulSets
2. **Docker Swarm**: Use stack deploy with replicas
3. **Service mesh**: For MCP discovery and routing

### Resource Optimization

```yaml
# docker-compose.mcps.yml - resource limits
services:
  mcp-grafana-vattenfall:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
```

## File Structure Proposal

```
sm3_agent/
├── mcp_servers.json          # Customer -> MCP mappings
├── mcp_credentials.env       # All MCP credentials (gitignored)
├── docker-compose.mcps.yml   # Generated MCP containers
├── scripts/
│   ├── generate_mcp_compose.py
│   └── manage_mcps.py        # Start/stop/status commands
└── mcps/
    ├── alertmanager-mcp/     # AlertManager MCP source
    ├── genesys-cloud-mcp/    # Genesys Cloud MCP source
    └── README.md
```

## API Changes

### New Endpoints

```python
# Get customer info including available MCP types
GET /api/customers/{name}
Response: {
  "name": "Vattenfall DE",
  "mcp_types": ["grafana", "alertmanager", "genesys"],
  "tools": ["search_dashboards", "get_alerts", "search_queues", ...]
}

# Get all customers with their capabilities
GET /api/customers
Response: {
  "customers": [
    {"name": "Vattenfall DE", "mcp_types": ["grafana", "alertmanager", "genesys"]},
    {"name": "Segurcaixa", "mcp_types": ["grafana", "alertmanager"]}
  ],
  "current": "Vattenfall DE"
}

# Enhanced switch response
POST /api/customers/switch
Response: {
  "success": true,
  "customer": "Vattenfall DE",
  "connected_mcps": ["grafana", "alertmanager", "genesys"],
  "failed_mcps": [],
  "tool_count": 75
}
```

## Next Steps

1. [ ] **Finalize config format**: Review proposed `mcp_servers.json` structure
2. [ ] **Create docker-compose generator**: Script to build MCP docker-compose
3. [ ] **Update MCPServer dataclass**: Add config field for credentials
4. [ ] **Build Genesys Cloud MCP image**: Dockerfile already exists
5. [ ] **Update frontend**: Show available integrations per customer
6. [ ] **Test with one customer**: Vattenfall DE with all 3 MCP types
7. [ ] **Roll out to other customers**: Add configs incrementally

## Questions to Resolve

1. **Credential management**: Store in `.env` or external secrets manager?
2. **Container startup**: All at once or on-demand?
3. **Health checks**: How to verify MCP servers are healthy?
4. **Failover**: What happens if one MCP type fails?
5. **Genesys regions**: Different OAuth endpoints per region?
