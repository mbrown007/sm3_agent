# AI Agent Chat App - Running Status

## ✅ Services Running

### Frontend (React + Vite)
- **Container**: grafana-agent-frontend-dev
- **URL**: http://localhost:3100
- **Status**: Running (Up 22 hours)
- **Internal**: http://172.19.0.3:3000

### Backend (Python + FastAPI)
- **Container**: grafana-agent-backend-dev
- **URL**: http://localhost:8000
- **Status**: Running (Up 22 hours)
- **API Docs**: http://localhost:8000/docs

### MCP Server (Grafana)
- **Container**: grafana-mcp-server-dev
- **URL**: http://localhost:8888
- **Status**: Running (Up 22 hours)

## Access the App

🌐 **Open in browser**: http://localhost:3100

## Quick Commands

```powershell
# View all services status
docker-compose -f docker-compose.dev.yml ps

# View frontend logs
docker-compose -f docker-compose.dev.yml logs -f frontend

# View backend logs
docker-compose -f docker-compose.dev.yml logs -f agent

# Restart services
docker-compose -f docker-compose.dev.yml restart

# Stop all services
docker-compose -f docker-compose.dev.yml down

# Rebuild and restart
docker-compose -f docker-compose.dev.yml up -d --build
```

## Architecture

```
┌─────────────────────────────────────────────┐
│   Browser: http://localhost:3100           │
│   (React Frontend - Vite Dev Server)       │
└──────────────────┬──────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────┐
│   Backend API: http://localhost:8000       │
│   (FastAPI + Uvicorn with hot-reload)      │
└──────────────────┬──────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────┐
│   MCP Server: http://localhost:8888        │
│   (Grafana MCP - Streamable HTTP)          │
└─────────────────────────────────────────────┘
```

## Features

- ✅ Hot-reload enabled for both frontend and backend
- ✅ Volume mounts for live code changes
- ✅ CORS configured for local development
- ✅ Connected to Grafana MCP server
- ✅ Knowledge base integration (/data/kb)
- ✅ Alert analysis integration (/data/alert-analyses)

## Notes

- Frontend has some npm audit warnings (2 moderate, 3 high) - run `npm audit fix` if needed
- Services have been running for 22 hours and are stable
- The app is in development mode with hot-reload enabled
