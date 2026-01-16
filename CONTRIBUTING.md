# Contributing to SM3 Agent

## Project Structure

```
sm3_agent/
├── docker-compose.yml      # Main compose - USE THIS for development
├── .env.example            # Environment template - copy to .env
│
├── sm3_agent/              # 🐍 Python backend (FastAPI + LangChain)
├── frontend/web/           # ⚛️ React frontend (Vite + TypeScript)
├── mcps/                   # 🔌 MCP servers
│   ├── mcp-grafana/        #    Grafana MCP (clone - use Docker image in prod)
│   ├── alertmanager-mcp/   #    AlertManager integration
│   └── genesys-cloud-mcp/  #    Genesys Cloud integration
│
├── docker/                 # 🐳 Alternative Docker configs
├── docs/                   # 📚 Documentation
├── kb/                     # 📖 Knowledge base articles
├── scripts/                # 🔧 Utility scripts
└── examples/               # 📁 Sample data files
```

## Development Setup

### Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local backend dev)
- Node.js 18+ (for local frontend dev)
- OpenAI API key

### Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/brownster/sm3_agent.git
cd sm3_agent
cp .env.example .env
# Edit .env with your API keys

# 2. Start services
docker compose up -d

# 3. Access at http://localhost:3100
```

### Local Development

**Backend:**
```bash
cd sm3_agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend/web
npm install
npm run dev
```

## Code Style

- **Python**: Follow PEP 8, use type hints
- **TypeScript**: Use ESLint config, prefer functional components
- **Commits**: Use conventional commits (feat:, fix:, docs:, etc.)

## Documentation

- Keep `README.md` concise - detailed docs go in `docs/`
- Archive completed/legacy docs in `docs/archive/`
- Update `docs/ARCHITECTURE_MULTI_MCP.md` for architectural changes
