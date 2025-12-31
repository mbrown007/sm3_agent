# Deployment Options

This project provides multiple docker-compose configurations for different deployment scenarios.

## Option 1: Laptop Deployment (Recommended for Your Setup)

**File**: `docker-compose.yml`

**Use Case**: Run frontend + backend on your laptop, with MCP server and Grafana on separate machines.

**What Runs Locally**:
- ✅ Agent Backend (from GHCR)
- ✅ Frontend UI (from GHCR)

**What's External**:
- ❌ MCP Server (on monitoring server)
- ❌ Grafana (on monitoring server)

**Setup**:
```bash
# 1. Pull pre-built images
docker pull ghcr.io/brownster/sm3_agent-agent:latest
docker pull ghcr.io/brownster/sm3_agent-frontend:latest

# 2. Configure environment
cp .env.example .env
nano .env

# Set these in .env:
# OPENAI_API_KEY=sk-...
# MCP_SERVER_URL=http://your-monitoring-server:8888/mcp
# GRAFANA_URL=https://your-grafana.com
# GRAFANA_TOKEN=glsa_...

# 3. Start services
docker-compose up -d

# 4. Access
# Frontend: http://localhost:3000
# Backend: http://localhost:8000
```

**Benefits**:
- Uses pre-built, tested images
- No build time needed
- Easy updates: `docker-compose pull && docker-compose up -d`
- Lightweight on laptop

---

## Option 2: Full Stack with Test Environment

**File**: `docker-compose.full.yml`

**Use Case**: Run everything locally including test Grafana, Prometheus, and Loki.

**What Runs Locally**:
- ✅ Agent Backend (built locally)
- ✅ Frontend UI (built locally)
- ✅ MCP Server (official image)
- ✅ Test Grafana instance
- ✅ Prometheus (optional, with profile)
- ✅ Loki (optional, with profile)

**Setup**:
```bash
# Start everything
docker-compose -f docker-compose.full.yml up -d

# Or with monitoring
COMPOSE_PROFILES=monitoring docker-compose -f docker-compose.full.yml up -d

# Or with test Grafana
COMPOSE_PROFILES=testing docker-compose -f docker-compose.full.yml up -d
```

**Benefits**:
- Complete local development environment
- No external dependencies
- Test with sample data
- Good for development/testing

---

## Option 3: Development Mode

**File**: `docker-compose.dev.yml`

**Use Case**: Local development with hot-reloading.

**What Runs**:
- ✅ Agent Backend (with auto-reload on code changes)
- ✅ Frontend UI (Vite dev server with HMR)
- ✅ MCP Server (official image)

**Setup**:
```bash
# Start in development mode
docker-compose -f docker-compose.dev.yml up

# Code changes auto-reload:
# - Backend: uvicorn --reload
# - Frontend: Vite HMR
```

**Benefits**:
- Fast development cycle
- Source maps for debugging
- Hot module replacement

---

## Comparison

| Feature | Laptop (Recommended) | Full Stack | Development |
|---------|---------------------|------------|-------------|
| File | `docker-compose.yml` | `docker-compose.full.yml` | `docker-compose.dev.yml` |
| Images | Pre-built (GHCR) | Build locally | Build locally |
| MCP Server | External ⚡ | Included | Included |
| Grafana | External ⚡ | Included (test) | External |
| Hot Reload | No | No | Yes |
| Build Time | None | ~5 min | ~2 min |
| Disk Usage | ~500MB | ~2GB | ~1GB |
| Best For | Production on laptop | Testing/Demo | Development |

---

## Updating Images

### Laptop Deployment (Pre-built)

```bash
# Pull latest images
docker-compose pull

# Recreate containers with new images
docker-compose up -d

# Or specify version tag
# docker-compose pull ghcr.io/brownster/sm3_agent-agent:v1.0.0
```

### Full Stack / Development (Built)

```bash
# Rebuild images
docker-compose -f docker-compose.full.yml build --no-cache

# Recreate containers
docker-compose -f docker-compose.full.yml up -d
```

---

## Environment Variables

### Laptop Deployment

**Required in .env**:
```bash
OPENAI_API_KEY=sk-...
MCP_SERVER_URL=http://monitoring-server:8888/mcp    # Your MCP server
GRAFANA_URL=https://your-grafana.com           # Your Grafana
GRAFANA_TOKEN=glsa_...
```

### Full Stack / Development

**Required in .env**:
```bash
OPENAI_API_KEY=sk-...
GRAFANA_URL=https://your-grafana.com
GRAFANA_TOKEN=glsa_...
# MCP_SERVER_URL is automatic (http://mcp-server:8888/mcp)
```

---

## Networking

### Laptop Deployment
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Metrics: http://localhost:8000/metrics

**External**:
- MCP Server: Your monitoring server
- Grafana: Your Grafana instance

### Full Stack
All services available locally:
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- Test Grafana: http://localhost:3001
- Prometheus: http://localhost:9090
- Loki: http://localhost:3100

---

## Troubleshooting

### Cannot Connect to MCP Server

```bash
# Test connectivity from agent container
docker exec grafana-agent-backend wget -O- http://mcp-server:8888/health

# Check if MCP server is accessible from laptop
curl http://your-monitoring-server:8888/health
```

### Images Not Found

```bash
# Login to GHCR (if private repo)
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin

# Pull images manually
docker pull ghcr.io/brownster/sm3_agent-agent:latest
docker pull ghcr.io/brownster/sm3_agent-frontend:latest
```

### Check Running Containers

```bash
# View status
docker-compose ps

# View logs
docker-compose logs -f agent
docker-compose logs -f frontend
```

---

## Your Setup (Laptop + Remote MCP)

Based on your requirements:

```bash
# 1. MCP Server (on monitoring server)
# Run as Go binary or Docker container
./mcp-grafana --transport streamable-http --address 0.0.0.0:8888

# 2. Laptop (this machine)
cp .env.example .env
# Edit .env with remote MCP_SERVER_URL
docker-compose up -d

# Access at http://localhost:3000
```

**Architecture**:
```
┌─────────────────┐
│  Your Laptop    │
│                 │
│  ┌──────────┐   │
│  │ Frontend │   │
│  │  :3000   │   │
│  └────┬─────┘   │
│       │         │
│  ┌────▼─────┐   │
│  │ Backend  │   │
│  │  :8000   │   │
│  └────┬─────┘   │
└───────┼─────────┘
        │ HTTP
        ▼
┌─────────────────┐
│ Monitoring      │
│ Server          │
│                 │
│  ┌──────────┐   │
│  │   MCP    │   │
│  │  Server  │◄──┼───► Grafana
│  │  :8888   │   │
│  └──────────┘   │
└─────────────────┘
```

Perfect for your use case! 🚀
