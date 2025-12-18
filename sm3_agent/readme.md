# SM3 Monitoring Agent

A production-ready chat assistant that connects to Grafana MCP server using LangChain. Features dynamic tool discovery, per-session memory isolation, and intelligent result formatting.

## ✨ Features

- 🔧 **Dynamic Tool Discovery:** Automatically discovers and exposes all 50+ Grafana MCP tools
- 🔒 **Session Isolation:** Per-user conversation memory for privacy and multi-tenancy
- 🛡️ **Robust Error Handling:** Comprehensive error handling with retry logic
- 🎨 **Smart Formatting:** Intelligent formatting of Prometheus, Loki, and dashboard results
- 🔐 **Secure Configuration:** Configurable CORS, environment validation
- 🚀 **Modern Architecture:** Uses latest LangChain patterns (create_react_agent)
- 📊 **Production Ready:** Logging, monitoring, timeouts, and resource management

## Structure
- `backend/app`: FastAPI entrypoint and configuration
- `backend/agents`: Agent orchestration with per-session memory
- `backend/tools`: MCP client with lifecycle management and result formatting
- `backend/schemas`: Pydantic schemas for chat requests/responses
- `backend/utils`: Logging, prompts, and utilities
- `frontend/chainlit_app.py`: Interactive chat UI with error handling

## Getting Started

### Prerequisites
- Python 3.11+
- Access to Grafana MCP server (local or remote)
- OpenAI API key

### Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set required environment variables:
   ```bash
   # Required
   export OPENAI_API_KEY=sk-your-openai-key
   export MCP_SERVER_URL=http://localhost:3001/mcp

   # Optional (with defaults)
   export OPENAI_MODEL=gpt-4o
   export CORS_ORIGINS=http://localhost:3000,http://localhost:8001
   export CORS_ALLOW_CREDENTIALS=true
   export ENABLE_LANGCHAIN_TRACING=false
   ```

3. Run the FastAPI service:
   ```bash
   uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. Run the Chainlit UI:
   ```bash
   chainlit run frontend/chainlit_app.py
   ```

### API Endpoints

- **POST /api/chat**: Send chat messages to the agent
  ```json
  {
    "message": "List all Prometheus datasources",
    "session_id": "user-123"
  }
  ```

- **GET /health**: Health check endpoint
  ```json
  {
    "status": "ok",
    "service": "grafana-mcp-chat"
  }
  ```

## Docker
- Build locally from the root Dockerfile:
  ```bash
  docker build -t sm3-agent:local .
  docker run --rm -p 8000:8000 \
    -e OPENAI_API_KEY=<your-key> \
    -e MCP_SERVER_URL=http://mcp:3001/mcp \
    sm3-agent:local
  ```
- Pull from GHCR (built by the GitHub Action) and run a single container:
  ```bash
  docker run --rm \
    -p 8000:8000 -p 8001:8001 \
    -e OPENAI_API_KEY=<your-key> \
    -e MCP_SERVER_URL=http://mcp:3001/mcp \
    -e SERVICE=all \
    ghcr.io/brownster/sm3_agent:latest
  ```
  The image now ships a small entrypoint so you can choose what to start:
  - `SERVICE=backend` (default): only the FastAPI API on `BACKEND_PORT` (default `8000`).
  - `SERVICE=chainlit`: only the Chainlit UI on `CHAINLIT_PORT` (default `8001`).
  - `SERVICE=all`: run both processes in one container (expose both ports).
- Publish to GHCR via the "Manual Docker Build" GitHub Action. Trigger the workflow with a `version` input (e.g., `v0.1.0`) to build and push `ghcr.io/<org>/<repo>:<version>` using the same Dockerfile.

### Example docker-compose
The example assumes an MCP server is reachable at `http://mcp:3001/mcp` (run it as another service or adjust the URL).
```yaml
services:
  backend:
    image: ghcr.io/<org>/<repo>:<tag>
    restart: unless-stopped
    environment:
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      MCP_SERVER_URL: http://mcp:3001/mcp
    ports:
      - "8000:8000"

  chainlit:
    image: ghcr.io/<org>/<repo>:<tag>
    command: ["chainlit", "run", "frontend/chainlit_app.py", "-h", "0.0.0.0", "-p", "8001"]
    restart: unless-stopped
    environment:
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      MCP_SERVER_URL: http://mcp:3001/mcp
    depends_on:
      - backend
    ports:
      - "8001:8001"
```
