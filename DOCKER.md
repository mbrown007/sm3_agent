# Docker Deployment Guide

Complete guide for deploying Grafana Web Agent using Docker and Docker Compose.

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Services](#services)
- [Configuration](#configuration)
- [Development Mode](#development-mode)
- [Production Deployment](#production-deployment)
- [Troubleshooting](#troubleshooting)

## Quick Start

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- At least 2GB RAM available
- Anthropic API key
- Grafana instance with API token

### 1. Clone and Configure

```bash
# Clone repository
git clone https://github.com/your-org/grafana-web-agent.git
cd grafana-web-agent

# Copy environment template
cp .env.example .env

# Edit .env with your values
nano .env
```

### 2. Start Services

```bash
# Start all core services (mcp-server, agent, frontend)
docker-compose up -d

# Or start with optional monitoring services
COMPOSE_PROFILES=monitoring docker-compose up -d

# Or start with test Grafana instance
COMPOSE_PROFILES=testing docker-compose up -d

# Start everything
COMPOSE_PROFILES=testing,monitoring docker-compose up -d
```

### 3. Verify Deployment

```bash
# Check service status
docker-compose ps

# View logs
docker-compose logs -f

# Test endpoints
curl http://localhost:8000/health    # Backend health
curl http://localhost:3000/health    # Frontend health
curl http://localhost:8888/health    # MCP server health
```

## Architecture

```
┌─────────────────┐
│   Web Browser   │
└────────┬────────┘
         │ HTTP :3000
         ▼
┌─────────────────┐
│  React Frontend │  (nginx)
│  (Container)    │
└────────┬────────┘
         │ HTTP :8000
         ▼
┌─────────────────┐
│  Python Agent   │  (FastAPI + LangChain)
│   (Container)   │
└────────┬────────┘
         │ HTTP :8888
         ▼
┌─────────────────┐        ┌─────────────────┐
│  MCP Server     │───────▶│  Grafana API    │
│  (Container)    │        │  (External)     │
└─────────────────┘        └─────────────────┘
         │
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────┐
│Prometheus│ │ Loki  │
└────────┘ └────────┘
```

## Services

### Core Services (Always Running)

#### 1. mcp-server

**Image**: Built from `./mcp-grafana/Dockerfile`
**Port**: 8888
**Description**: Grafana MCP server that provides tools for querying Grafana

**Environment Variables**:
- `GRAFANA_URL` - Your Grafana instance
- `GRAFANA_TOKEN` - API token for authentication

**Health Check**: `http://localhost:8888/health`

#### 2. agent

**Image**: Built from `./sm3_agent/Dockerfile`
**Port**: 8000
**Description**: Python backend with FastAPI, LangChain agent, caching, and monitoring

**Environment Variables**:
- `ANTHROPIC_API_KEY` - Claude API key
- `MCP_SERVER_URL` - URL to MCP server (default: http://mcp-server:8888)
- `GRAFANA_URL` - Your Grafana instance
- `GRAFANA_TOKEN` - API token
- `MODEL` - Claude model to use
- `CORS_ORIGINS` - Allowed CORS origins

**Health Check**: `http://localhost:8000/health`

**Exposed Endpoints**:
- `/api/chat` - Chat API
- `/api/chat/stream` - Streaming chat
- `/monitoring/*` - Monitoring endpoints
- `/metrics` - Prometheus metrics
- `/docs` - Swagger API docs

#### 3. frontend

**Image**: Built from `./frontend/web/Dockerfile`
**Port**: 3000 → 80 (nginx)
**Description**: React web UI served by nginx

**Build Args**:
- `VITE_API_URL` - Backend API URL

**Health Check**: `http://localhost:3000/health`

### Optional Services (Profiles)

#### Profile: testing

Start with: `COMPOSE_PROFILES=testing docker-compose up -d`

**grafana** - Test Grafana instance with sample data
- Port: 3001
- Username: admin
- Password: admin
- Includes provisioned dashboards and datasources

#### Profile: monitoring

Start with: `COMPOSE_PROFILES=monitoring docker-compose up -d`

**prometheus** - Metrics storage and querying
- Port: 9090
- Scrapes metrics from agent on `/metrics`
- Web UI: http://localhost:9090

**loki** - Log aggregation
- Port: 3100
- Ready to receive logs
- Query logs via Grafana

## Configuration

### Environment Variables

See `.env.example` for all available options. Key variables:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-api03-...
GRAFANA_URL=https://your-grafana.com
GRAFANA_TOKEN=glsa_...

# Optional
MODEL=claude-3-5-sonnet-20241022
CORS_ORIGINS=http://localhost:3000
CACHE_MAX_SIZE=1000
CACHE_DEFAULT_TTL=300
```

### Volume Mounts

Data is persisted in Docker volumes:

- `grafana-data` - Grafana configuration and dashboards
- `prometheus-data` - Prometheus metrics storage
- `loki-data` - Loki logs storage

```bash
# List volumes
docker volume ls | grep grafana-agent

# Inspect volume
docker volume inspect grafana-agent_prometheus-data

# Backup volume
docker run --rm -v grafana-agent_prometheus-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/prometheus-backup.tar.gz -C /data .

# Restore volume
docker run --rm -v grafana-agent_prometheus-data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/prometheus-backup.tar.gz -C /data
```

## Development Mode

For local development with hot-reloading:

```bash
# Start development environment
docker-compose -f docker-compose.dev.yml up

# This provides:
# - Backend with uvicorn --reload
# - Frontend with Vite dev server + HMR
# - Volume mounts for code changes
```

**Development Features**:
- Backend auto-reloads on Python file changes
- Frontend hot module replacement (HMR)
- Source maps enabled
- Debug logging

**Ports**:
- Frontend (Vite): 3000
- Backend (FastAPI): 8000
- MCP Server: 8888

## Production Deployment

### Docker Compose

```bash
# Pull latest images (if using registry)
docker-compose pull

# Start with production settings
docker-compose up -d

# Scale services if needed
docker-compose up -d --scale agent=3

# Update services
docker-compose up -d --no-deps --build agent
```

### Using GitHub Container Registry

```bash
# Pull pre-built images
docker pull ghcr.io/your-org/grafana-web-agent-mcp-server:latest
docker pull ghcr.io/your-org/grafana-web-agent-agent:latest
docker pull ghcr.io/your-org/grafana-web-agent-frontend:latest

# Use docker-compose with registry images
version: '3.8'
services:
  mcp-server:
    image: ghcr.io/your-org/grafana-web-agent-mcp-server:latest
  agent:
    image: ghcr.io/your-org/grafana-web-agent-agent:latest
  frontend:
    image: ghcr.io/your-org/grafana-web-agent-frontend:latest
```

### Kubernetes

Example Kubernetes deployment:

```bash
# Create namespace
kubectl create namespace grafana-agent

# Create secrets
kubectl create secret generic grafana-agent-secrets \
  --namespace=grafana-agent \
  --from-literal=anthropic-api-key=$ANTHROPIC_API_KEY \
  --from-literal=grafana-token=$GRAFANA_TOKEN

# Deploy (assuming k8s/ directory exists)
kubectl apply -f k8s/ -n grafana-agent

# Check status
kubectl get pods -n grafana-agent
kubectl logs -f deployment/grafana-agent-backend -n grafana-agent
```

### Docker Swarm

```bash
# Initialize swarm
docker swarm init

# Create secrets
echo $ANTHROPIC_API_KEY | docker secret create anthropic_api_key -
echo $GRAFANA_TOKEN | docker secret create grafana_token -

# Deploy stack
docker stack deploy -c docker-compose.yml grafana-agent

# Check services
docker service ls
docker service logs grafana-agent_agent
```

## Monitoring

### Prometheus Metrics

Agent exposes Prometheus metrics on `/metrics`:

```bash
# View metrics
curl http://localhost:8000/metrics

# Configure Prometheus to scrape
# See prometheus.yml for configuration
```

**Available Metrics**:
- `agent_chat_requests_total` - Total chat requests
- `agent_chat_duration_seconds` - Request duration
- `agent_tool_invocations_total` - Tool usage
- `agent_cache_hit_rate` - Cache performance
- `agent_monitoring_anomalies_detected` - Anomalies found

### Logs

View logs from all services:

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f agent

# Last 100 lines
docker-compose logs --tail=100 agent

# Filter for errors
docker-compose logs agent | grep ERROR
```

## Troubleshooting

### Service Won't Start

```bash
# Check service status
docker-compose ps

# View logs
docker-compose logs service-name

# Restart service
docker-compose restart service-name

# Rebuild and restart
docker-compose up -d --build service-name
```

### Connection Issues

```bash
# Check network
docker network inspect grafana-agent_grafana-agent-network

# Test connectivity between services
docker-compose exec agent ping mcp-server
docker-compose exec frontend wget -O- http://agent:8000/health
```

### Performance Issues

```bash
# Check resource usage
docker stats

# Limit resources in docker-compose.yml:
services:
  agent:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          memory: 1G
```

### Clean Up

```bash
# Stop all services
docker-compose down

# Remove volumes (WARNING: deletes all data)
docker-compose down -v

# Remove images
docker-compose down --rmi all

# Complete cleanup
docker-compose down -v --rmi all --remove-orphans
```

## Security Best Practices

1. **Never commit `.env` files** - Use `.env.example` as template
2. **Use secrets management** - For production, use Docker secrets or Kubernetes secrets
3. **Update base images regularly** - Rebuild images with latest security patches
4. **Limit container resources** - Prevent resource exhaustion
5. **Use non-root users** - All containers run as non-root by default
6. **Enable TLS** - Use reverse proxy (nginx/traefik) with SSL certificates
7. **Restrict network access** - Use firewall rules and security groups

## CI/CD Integration

GitHub Actions automatically builds and pushes images on:
- Push to `main` branch
- New version tags (`v*.*.*`)
- Pull requests (build only)

See `.github/workflows/docker-build-push.yml` for details.

## Support

For issues and questions:
- GitHub Issues: https://github.com/your-org/grafana-web-agent/issues
- Documentation: See `README.md` and other docs
- API Documentation: http://localhost:8000/docs (when running)
