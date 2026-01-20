# SM3 Agent

An intelligent AI chat agent for multi-customer monitoring infrastructure, supporting Grafana, AlertManager, and Genesys Cloud.

<img width="1644" height="922" alt="image" src="https://github.com/user-attachments/assets/d7870da7-f3b2-43dd-9fda-6e9e9abdaf89" />


## Features

- 🤖 **AI-Powered Chat** - Natural language queries using GPT-4
- 📊 **Rich Artifacts** - Visual reports with charts, tables, and metric cards
- 🔄 **Multi-MCP Support** - Grafana, AlertManager, Genesys Cloud integrations
- 👥 **Multi-Customer** - Switch between customers dynamically
- 📈 **Proactive Monitoring** - Background anomaly detection
- ⚡ **Real-time Streaming** - Server-Sent Events for live responses
- 🎯 **Smart Caching** - TTL-based LRU cache for performance

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings:
#   OPENAI_API_KEY=sk-...
#   GRAFANA_URL=https://your-grafana.com
#   GRAFANA_TOKEN=your-service-account-token
```

### 2. Start Services

```bash
docker compose up -d
```

### 3. Access

| Service | URL |
|---------|-----|
| Web UI | http://localhost:3100 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

## Project Structure

```
sm3_agent/
├── docker-compose.yml      # Main compose file
├── .env.example            # Environment template
├── README.md               # This file
│
├── sm3_agent/              # Python backend
│   ├── backend/
│   │   ├── agents/         # LangChain agent, proactive monitoring
│   │   ├── api/            # FastAPI routes
│   │   ├── app/            # App configuration
│   │   ├── containers/     # Dynamic MCP container management
│   │   ├── intelligence/   # Anomaly detection
│   │   ├── tools/          # MCP client, caching
│   │   └── utils/          # Prompts, logging
│   ├── mcp_servers.json    # Customer/MCP configuration
│   └── requirements.txt
│
├── frontend/web/           # React frontend
│   └── src/
│       ├── components/     # Artifact, MarkdownContent, Layout
│       ├── pages/          # ChatPage, MonitoringPage
│       └── services/       # API client
│
├── mcps/                   # MCP server implementations
│   ├── mcp-grafana/        # Grafana MCP (clone of grafana/mcp-grafana)
│   ├── alertmanager-mcp/   # AlertManager integration
│   └── genesys-cloud-mcp/  # Genesys Cloud integration
│
├── docker/                 # Docker configurations
│   ├── docker-compose.*.yml  # Alternative compose files
│   ├── prometheus.yml
│   └── ...
│
├── docs/                   # Documentation
│   ├── DOCKER.md           # Docker setup guide
│   ├── ARCHITECTURE_MULTI_MCP.md
│   ├── DEPLOYMENT_OPTIONS.md
│   └── archive/            # Legacy/completed docs
│
├── kb/                     # Knowledge base articles
├── scripts/                # Utility scripts
└── examples/               # Sample data files
```

## Configuration

### Customer Configuration

Edit `sm3_agent/mcp_servers.json` to configure customers and their MCP servers:

```json
{
  "customers": {
    "Acme Corp": {
      "mcp_servers": {
        "grafana": {
          "url": "https://maas-acme.mon.example.com",
          "type": "grafana"
        },
        "alertmanager": {
          "url": "https://maas-acme.mon.example.com:9093",
          "type": "alertmanager"
        }
      },
      "has_genesys": true,
      "genesys_region": "mypurecloud.com"
    }
  }
}
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key | ✅ |
| `GRAFANA_URL` | Default Grafana URL | ✅ |
| `GRAFANA_TOKEN` | Grafana service account token | ✅ |
| `OPENAI_MODEL` | Model to use (default: gpt-4o) | ❌ |
| `CORS_ORIGINS` | Allowed origins | ❌ |

## Development

### Backend Development

```bash
cd sm3_agent
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

### Frontend Development

```bash
cd frontend/web
npm install
npm run dev
```

### Rebuild Containers

```bash
docker compose build --no-cache
docker compose up -d
```

## Docker Compose Variants

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Main development setup (recommended) |
| `docker/docker-compose.full.yml` | Full stack with all services |
| `docker/docker-compose.exporters.yml` | Prometheus exporters for testing |
| `docker/docker-compose.mcp-test.yml` | MCP server testing |

## Documentation

| Document | Description |
|----------|-------------|
| [docs/DOCKER.md](docs/DOCKER.md) | Docker setup guide |
| [docs/ARCHITECTURE_MULTI_MCP.md](docs/ARCHITECTURE_MULTI_MCP.md) | Multi-MCP architecture |
| [docs/DEPLOYMENT_OPTIONS.md](docs/DEPLOYMENT_OPTIONS.md) | Deployment scenarios |
| [docs/GRAFANA_ALERT_WEBHOOK_SETUP.md](docs/GRAFANA_ALERT_WEBHOOK_SETUP.md) | Alert webhook config |

## Screenshots

<details>
<summary>Click to view more screenshots</summary>

<img width="1601" alt="Chat Interface" src="https://github.com/user-attachments/assets/28ee2047-22f3-438d-b1ac-d9064ec6b110" />

<img width="1558" alt="Tool Calls" src="https://github.com/user-attachments/assets/d33b1e94-dfb1-4621-822a-3f9efe5902e6" />

<img width="1562" alt="Dashboard Search" src="https://github.com/user-attachments/assets/c77628df-8acf-4d8b-8fca-47c28b8c34ee" />

</details>

## License

MIT







