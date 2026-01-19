# MCP HTTP/SSE Transport Implementation Roadmap

## Executive Summary
AlertManager and Genesys Cloud MCPs currently only support **stdio transport** (stdin/stdout). The SM3 Agent architecture requires **Streamable HTTP transport** for dynamic, multi-customer containerized deployment. This roadmap outlines the implementation plan to add HTTP/SSE support to both MCPs.

> **⚠️ CRITICAL UPDATE (v2.0)**: This document has been revised based on analysis of the official MCP TypeScript SDK v2 implementation. The original plan had significant gaps in session management and transport handling.

## Current State Analysis

### Working: Grafana MCP ✅
- **Transport**: Streamable HTTP (Go-based native implementation)
- **Command**: `--transport streamable-http --address 0.0.0.0:8888`
- **Endpoint**: `/mcp` (POST for requests, GET for SSE streams)
- **Status**: Fully functional in containerized environment

### Blocked: AlertManager MCP ❌
- **Current Transport**: stdio only (StdioServerTransport)
- **SDK**: `@modelcontextprotocol/sdk` v1.6.1 → **needs full v2 migration**
- **Language**: TypeScript/Node.js
- **Issue**: No HTTP transport, containers crash-loop expecting stdin

### Blocked: Genesys Cloud MCP ❌
- **Current Transport**: stdio only (StdioServerTransport)
- **SDK**: `@modelcontextprotocol/sdk` v1.18.2 → **needs v2 migration**
- **Language**: TypeScript/Node.js
- **Issue**: No HTTP transport, containers crash-loop expecting stdin

---

## MCP SDK v2 Architecture (Critical Understanding)

### Package Structure
SDK v2 splits functionality into separate packages:

| Package | Purpose |
|---------|---------|
| `@modelcontextprotocol/server` | Core MCP server (`McpServer`, `isInitializeRequest`) |
| `@modelcontextprotocol/node` | **`NodeStreamableHTTPServerTransport`** - the key class |
| `@modelcontextprotocol/express` | Express helpers (`createMcpExpressApp`) |
| `zod` | Schema validation (required peer dependency) |

### Session-Based Transport Architecture
**Critical**: Unlike simple HTTP servers, MCP requires **persistent sessions**:

```
┌─────────────┐         POST /mcp          ┌─────────────────────────┐
│   Client    │ ─────────────────────────▶ │    Express Handler      │
│             │  (Mcp-Session-Id header)   │                         │
└─────────────┘                            │  ┌───────────────────┐  │
                                           │  │ Session Store     │  │
      ▲                                    │  │ ───────────────── │  │
      │    SSE Stream                      │  │ session-1 → T1    │  │
      │                                    │  │ session-2 → T2    │  │
      └────────────────────────────────────│  │ session-3 → T3    │  │
           (server-initiated messages)     │  └───────────────────┘  │
                                           │                         │
                                           │  Each T = NodeStreamable│
                                           │  HTTPServerTransport    │
                                           └─────────────────────────┘
```

Each client session needs its **own transport instance** that:
1. Gets created on `initialize` request
2. Stores session ID in `Mcp-Session-Id` header
3. Handles all subsequent requests for that session
4. Cleans up when session terminates

### Official Implementation Pattern
From `typescript-sdk/examples/server/src/simpleStreamableHttp.ts` (715 lines):

```typescript
import { randomUUID } from 'node:crypto';
import { createMcpExpressApp } from '@modelcontextprotocol/express';
import { NodeStreamableHTTPServerTransport } from '@modelcontextprotocol/node';
import { McpServer, isInitializeRequest } from '@modelcontextprotocol/server';
import type { Request, Response } from 'express';

// Session storage - CRITICAL for multi-client support
const transports: Record<string, NodeStreamableHTTPServerTransport> = {};

const app = createMcpExpressApp();

// POST handler - must handle both init and subsequent requests
app.post('/mcp', async (req: Request, res: Response) => {
    const sessionId = req.headers['mcp-session-id'] as string | undefined;
    
    if (sessionId && transports[sessionId]) {
        // Existing session - reuse transport
        await transports[sessionId].handleRequest(req, res, req.body);
    } else if (!sessionId && isInitializeRequest(req.body)) {
        // NEW session - create transport
        const transport = new NodeStreamableHTTPServerTransport({
            sessionIdGenerator: () => randomUUID(),
            onsessioninitialized: (id) => {
                console.log(`Session initialized: ${id}`);
                transports[id] = transport;
            }
        });
        
        // Cleanup on close
        transport.onclose = () => {
            const sid = transport.sessionId;
            if (sid && transports[sid]) {
                delete transports[sid];
            }
        };
        
        // Connect MCP server to transport BEFORE handling request
        const server = createMcpServer();  // Your server with tools
        await server.connect(transport);
        await transport.handleRequest(req, res, req.body);
    } else {
        res.status(400).json({
            jsonrpc: '2.0',
            error: { code: -32000, message: 'Invalid session' },
            id: null
        });
    }
});

// GET handler - for SSE streams (server-initiated messages)
app.get('/mcp', async (req: Request, res: Response) => {
    const sessionId = req.headers['mcp-session-id'] as string | undefined;
    if (!sessionId || !transports[sessionId]) {
        return res.status(400).send('Invalid or missing session ID');
    }
    await transports[sessionId].handleRequest(req, res);
});

// DELETE handler - session termination (MCP spec requirement)
app.delete('/mcp', async (req: Request, res: Response) => {
    const sessionId = req.headers['mcp-session-id'] as string | undefined;
    if (!sessionId || !transports[sessionId]) {
        return res.status(400).send('Invalid session');
    }
    await transports[sessionId].handleRequest(req, res);
});

app.listen(8080);
```

---

## Implementation Strategy

### Phase 1: AlertManager MCP - HTTP Transport (Priority 1)

#### Step 1.1: Update Dependencies
**File**: `mcps/alertmanager-mcp/package.json`

```json
{
  "name": "alertmanager-mcp",
  "version": "2.0.0",
  "type": "module",
  "main": "build/index.js",
  "dependencies": {
    "@modelcontextprotocol/server": "^2.0.0",
    "@modelcontextprotocol/node": "^2.0.0",
    "@modelcontextprotocol/express": "^2.0.0",
    "express": "^4.18.2",
    "zod": "^3.24.2"
  },
  "devDependencies": {
    "@types/express": "^4.17.21",
    "@types/node": "^22.13.10",
    "typescript": "^5.8.2"
  }
}
```

**Commands**:
```bash
cd mcps/alertmanager-mcp
rm -rf node_modules package-lock.json
npm install @modelcontextprotocol/server@latest \
            @modelcontextprotocol/node@latest \
            @modelcontextprotocol/express@latest \
            express zod
npm install -D @types/express @types/node typescript
```

#### Step 1.2: Refactor Server Architecture
**File**: `mcps/alertmanager-mcp/src/index.ts`

**Current Structure** (400 lines, stdio-only):
```typescript
// Current - all in one file
const server = new McpServer({ name: "alertmanager", version: "1.0.0" });
server.tool("get-alerts", ...);
server.tool("create-silence", ...);
// ... more tools ...

async function main() {
    const transport = new StdioServerTransport();
    await server.connect(transport);
}
```

**New Structure** (modular, dual-transport):

```
mcps/alertmanager-mcp/src/
├── index.ts           # Entry point with CLI parsing
├── server.ts          # MCP server factory with all tools
├── transports/
│   ├── stdio.ts       # Stdio transport (backward compat)
│   └── http.ts        # HTTP/SSE transport (new)
└── tools/
    ├── alerts.ts      # get-alerts, get-alert-details
    ├── silences.ts    # create-silence, get-silences, delete-silence
    └── groups.ts      # get-alert-groups
```

#### Step 1.3: Create Server Factory
**File**: `mcps/alertmanager-mcp/src/server.ts`

```typescript
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";

const DEFAULT_ALERTMANAGER_URL = "http://localhost:9093";
const DEFAULT_TIMEOUT = 10000;

async function fetchFromAlertmanager(path: string, options: RequestInit = {}): Promise<any> {
    const baseUrl = process.env.ALERTMANAGER_URL || DEFAULT_ALERTMANAGER_URL;
    const url = `${baseUrl}/api/v2/${path}`;
    // ... existing fetch logic ...
}

export function createAlertmanagerServer(): McpServer {
    const server = new McpServer({
        name: "alertmanager",
        version: "2.0.0"
    });

    // Register all tools
    server.registerTool(
        "get-alerts",
        {
            description: "Retrieves current alerts from Alertmanager",
            inputSchema: {
                filter: z.string().optional().describe("Filter query"),
                silenced: z.boolean().optional(),
                inhibited: z.boolean().optional(),
                active: z.boolean().optional().default(true)
            }
        },
        async ({ filter, silenced, inhibited, active }) => {
            // ... existing implementation ...
        }
    );

    // ... register other tools ...

    return server;
}
```

#### Step 1.4: Implement HTTP Transport
**File**: `mcps/alertmanager-mcp/src/transports/http.ts`

```typescript
import { randomUUID } from 'node:crypto';
import { createMcpExpressApp } from '@modelcontextprotocol/express';
import { NodeStreamableHTTPServerTransport } from '@modelcontextprotocol/node';
import { isInitializeRequest, McpServer } from '@modelcontextprotocol/server';
import type { Request, Response } from 'express';
import { createAlertmanagerServer } from '../server.js';

// Session storage
const transports: Record<string, NodeStreamableHTTPServerTransport> = {};
const servers: Record<string, McpServer> = {};

export async function startHttpTransport(port: number): Promise<void> {
    const app = createMcpExpressApp();

    // Health check endpoint (for container manager)
    app.get('/health', (req, res) => {
        res.json({ status: 'ok', sessions: Object.keys(transports).length });
    });

    // POST /mcp - Handle JSON-RPC requests
    app.post('/mcp', async (req: Request, res: Response) => {
        const sessionId = req.headers['mcp-session-id'] as string | undefined;

        try {
            if (sessionId && transports[sessionId]) {
                // Existing session
                await transports[sessionId].handleRequest(req, res, req.body);
            } else if (!sessionId && isInitializeRequest(req.body)) {
                // New session
                const transport = new NodeStreamableHTTPServerTransport({
                    sessionIdGenerator: () => randomUUID(),
                    onsessioninitialized: (id) => {
                        console.error(`[AlertManager MCP] Session initialized: ${id}`);
                        transports[id] = transport;
                    }
                });

                transport.onclose = () => {
                    const sid = transport.sessionId;
                    if (sid) {
                        console.error(`[AlertManager MCP] Session closed: ${sid}`);
                        delete transports[sid];
                        delete servers[sid];
                    }
                };

                // Create fresh server instance for this session
                const server = createAlertmanagerServer();
                if (transport.sessionId) {
                    servers[transport.sessionId] = server;
                }

                await server.connect(transport);
                await transport.handleRequest(req, res, req.body);
            } else {
                res.status(400).json({
                    jsonrpc: '2.0',
                    error: { code: -32000, message: 'Bad Request: No valid session' },
                    id: null
                });
            }
        } catch (error) {
            console.error('[AlertManager MCP] Error:', error);
            if (!res.headersSent) {
                res.status(500).json({
                    jsonrpc: '2.0',
                    error: { code: -32603, message: 'Internal error' },
                    id: null
                });
            }
        }
    });

    // GET /mcp - SSE stream for server-initiated messages
    app.get('/mcp', async (req: Request, res: Response) => {
        const sessionId = req.headers['mcp-session-id'] as string | undefined;
        if (!sessionId || !transports[sessionId]) {
            res.status(400).send('Invalid or missing session ID');
            return;
        }
        await transports[sessionId].handleRequest(req, res);
    });

    // DELETE /mcp - Session termination
    app.delete('/mcp', async (req: Request, res: Response) => {
        const sessionId = req.headers['mcp-session-id'] as string | undefined;
        if (!sessionId || !transports[sessionId]) {
            res.status(400).send('Invalid session');
            return;
        }
        await transports[sessionId].handleRequest(req, res);
    });

    // Start server
    app.listen(port, '0.0.0.0', () => {
        console.error(`[AlertManager MCP] HTTP server listening on http://0.0.0.0:${port}/mcp`);
    });

    // Graceful shutdown
    process.on('SIGINT', async () => {
        console.error('[AlertManager MCP] Shutting down...');
        for (const [sessionId, transport] of Object.entries(transports)) {
            try {
                await transport.close();
            } catch (e) {
                console.error(`Error closing session ${sessionId}:`, e);
            }
        }
        process.exit(0);
    });
}
```

#### Step 1.5: Implement Stdio Transport (Backward Compat)
**File**: `mcps/alertmanager-mcp/src/transports/stdio.ts`

```typescript
import { StdioServerTransport } from '@modelcontextprotocol/server/stdio';
import { createAlertmanagerServer } from '../server.js';

export async function startStdioTransport(): Promise<void> {
    const server = createAlertmanagerServer();
    const transport = new StdioServerTransport();
    await server.connect(transport);
    console.error('[AlertManager MCP] Started on stdio');
}
```

#### Step 1.6: Update Entry Point
**File**: `mcps/alertmanager-mcp/src/index.ts`

```typescript
#!/usr/bin/env node

import { startHttpTransport } from './transports/http.js';
import { startStdioTransport } from './transports/stdio.js';

function parseArgs(args: string[]): { transport: 'stdio' | 'http'; port: number } {
    const transportIdx = args.indexOf('--transport');
    const portIdx = args.indexOf('--port');
    
    return {
        transport: transportIdx >= 0 && args[transportIdx + 1] === 'http' ? 'http' : 'stdio',
        port: portIdx >= 0 ? parseInt(args[portIdx + 1], 10) : 8080
    };
}

async function main() {
    const { transport, port } = parseArgs(process.argv.slice(2));
    
    console.error(`[AlertManager MCP] Starting with transport: ${transport}`);
    
    if (transport === 'http') {
        await startHttpTransport(port);
    } else {
        await startStdioTransport();
    }
}

main().catch((error) => {
    console.error('[AlertManager MCP] Fatal error:', error);
    process.exit(1);
});
```

#### Step 1.7: Update Dockerfile
**File**: `mcps/alertmanager-mcp/Dockerfile`

```dockerfile
# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY src/ ./src/
COPY tsconfig.json ./
RUN npm run build

# Production stage
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --only=production
COPY --from=builder /app/build ./build

# Default to HTTP transport for containerized deployment
ENV NODE_ENV=production
EXPOSE 8080

ENTRYPOINT ["node", "build/index.js"]
CMD ["--transport", "http", "--port", "8080"]
```

#### Step 1.8: Update Container Manager
**File**: `sm3_agent/backend/containers/manager.py`

```python
# Build command based on MCP type
command = None
if config.mcp_type == MCPType.GRAFANA:
    # Grafana uses /mcp endpoint
    command = ["--transport", "streamable-http", "--address", f"0.0.0.0:{config.internal_port}"]
elif config.mcp_type == MCPType.ALERTMANAGER:
    # AlertManager v2 uses /mcp endpoint with session management
    command = ["--transport", "http", "--port", str(config.internal_port)]
elif config.mcp_type == MCPType.GENESYS:
    # Genesys v2 uses /mcp endpoint with session management
    command = ["--transport", "http", "--port", str(config.internal_port)]
```

Also update the URL property in `ContainerConfig`:

```python
@property
def url(self) -> str:
    """Get the MCP server URL."""
    # All MCP types now use /mcp endpoint (v2 standard)
    return f"http://localhost:{self.port}/mcp"
```

And update health check to use `/health` endpoint:

```python
async def _wait_for_healthy(self, status: ContainerStatus, timeout: Optional[int] = None) -> ContainerStatus:
    # ...
    while time.time() - start_time < timeout:
        try:
            async with aiohttp.ClientSession() as session:
                # Use /health for health checks, /mcp for MCP protocol
                health_url = f"http://localhost:{status.config.port}/health"
                async with session.get(health_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        status.state = ContainerState.HEALTHY
                        return status
        except Exception:
            pass
        await asyncio.sleep(self._health_interval)
```

#### Step 1.9: Testing Plan

**1. Unit Testing (Local)**:
```bash
cd mcps/alertmanager-mcp
npm run build
node build/index.js --transport http --port 9300

# In another terminal:
# Health check
curl http://localhost:9300/health

# Initialize session
curl -X POST http://localhost:9300/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
# Response includes Mcp-Session-Id header

# List tools (with session)
curl -X POST http://localhost:9300/mcp \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: <session-id-from-above>" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2,"params":{}}'
```

**2. Container Testing**:
```bash
docker build -t sm3/alertmanager-mcp:latest ./mcps/alertmanager-mcp
docker run -p 9300:8080 \
  -e ALERTMANAGER_URL=https://maas-ng-segurcaixa.segurcaixa.services.sabio.co.uk:9093 \
  sm3/alertmanager-mcp:latest

# Test health and initialize
curl http://localhost:9300/health
```

**3. Integration Testing**:
- Restart backend: `docker restart grafana-agent-backend-dev`
- Switch to Segurcaixa in frontend
- Check container logs: `docker logs sm3-mcp-alertmanager-segurcaixa`
- Verify health indicators turn green
- Test in chat: "Show me current alerts from AlertManager"

#### Step 1.10: Estimated Timeline (Revised)
| Task | Estimated Time | Complexity |
|------|----------------|------------|
| Dependency update & package setup | 30 min | Low |
| Server factory refactoring | 2 hours | Medium |
| HTTP transport implementation | 3 hours | High |
| Stdio transport (backward compat) | 30 min | Low |
| Entry point & CLI | 30 min | Low |
| Dockerfile update | 15 min | Low |
| Local testing & debugging | 2-3 hours | Medium |
| Container testing | 1-2 hours | Medium |
| Integration testing | 1-2 hours | Medium |
| **Total** | **1-2 days** | |

---

### Phase 2: Genesys Cloud MCP - HTTP Transport (Priority 2)

#### Key Differences from AlertManager:
1. Already on SDK v1.18.2 (closer to v2)
2. Has OAuth authentication wrapper
3. More complex tool registrations (10 tools)
4. Uses external API (Genesys Platform Client)

#### Step 2.1: Dependencies
Same as AlertManager:
```bash
npm install @modelcontextprotocol/server@latest \
            @modelcontextprotocol/node@latest \
            @modelcontextprotocol/express@latest
```

#### Step 2.2: Architecture
```
mcps/genesys-cloud-mcp-server/src/
├── index.ts           # Entry point
├── server.ts          # MCP server factory
├── transports/
│   ├── stdio.ts
│   └── http.ts
├── auth/
│   └── OAuthClientCredentialsWrapper.ts  # Keep existing
└── tools/             # Keep existing tool structure
    ├── searchQueues.ts
    ├── queryQueueVolumes.ts
    └── ...
```

#### Step 2.3: OAuth Consideration
The existing `OAuthClientCredentialsWrapper` works with environment variables:
- `GENESYSCLOUD_REGION`
- `GENESYSCLOUD_OAUTHCLIENT_ID`
- `GENESYSCLOUD_OAUTHCLIENT_SECRET`

This doesn't change for HTTP transport - the wrapper is applied at tool registration, not transport level.

#### Step 2.4: Estimated Timeline
| Task | Estimated Time |
|------|----------------|
| Dependencies | 30 min |
| Server factory refactoring | 3 hours |
| HTTP transport | 2 hours |
| OAuth integration testing | 2 hours |
| Container testing | 2 hours |
| **Total** | **1-2 days** |

---

### Phase 3: Fallback - HTTP-to-Stdio Proxy (If Needed)

If SDK v2 migration proves too complex, create a lightweight proxy:

```
┌─────────────┐     HTTP     ┌──────────────┐    stdio    ┌─────────────┐
│   Backend   │ ───────────▶ │  HTTP Proxy  │ ──────────▶ │ MCP Server  │
│   (Python)  │              │  (Node.js)   │             │ (stdio mode)│
└─────────────┘              └──────────────┘             └─────────────┘
```

**Pros**: No MCP code changes needed
**Cons**: Extra complexity, session management still needed

**Recommendation**: Only use if Phase 1/2 encounter blocking issues with SDK v2.

---

## Risk Assessment

### Technical Risks (Updated)

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| SDK v2 API incompatibility | Medium | High | Follow official examples exactly |
| Session management bugs | Medium | High | Extensive testing with multiple clients |
| Memory leaks (session cleanup) | Low | Medium | Implement proper `onclose` handlers |
| OAuth token in HTTP context | Low | Low | Tokens are in env vars, not transport |

### Schedule Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Underestimated effort** | **High** | High | **Allocate 2 days per MCP** |
| TypeScript compilation issues | Medium | Medium | Use strict tsconfig, test incrementally |

---

## Success Criteria

### AlertManager MCP v2
- [ ] Builds without TypeScript errors
- [ ] Container starts with `--transport http --port 8080`
- [ ] `/health` endpoint returns 200 OK
- [ ] Initialize request creates session
- [ ] Session ID returned in `Mcp-Session-Id` header
- [ ] `tools/list` returns all 6 AlertManager tools
- [ ] `get-alerts` tool works with real AlertManager
- [ ] Session cleanup on disconnect
- [ ] No crash-loops or memory leaks

### Genesys Cloud MCP v2
- [ ] OAuth authentication works
- [ ] All 10 tools registered
- [ ] Queue search returns data
- [ ] Conversation sentiment works

### Integration
- [ ] Backend connects to all 3 MCP types
- [ ] Customer switch completes in <60s
- [ ] Frontend shows 3 green health indicators
- [ ] Agent can use tools from all MCPs

---

## References

- **Official SDK v2 Example**: https://github.com/modelcontextprotocol/typescript-sdk/blob/main/examples/server/src/simpleStreamableHttp.ts
- **SDK v2 Server Docs**: https://github.com/modelcontextprotocol/typescript-sdk/blob/main/docs/server.md
- **MCP Spec (Transports)**: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- **NodeStreamableHTTPServerTransport**: `@modelcontextprotocol/node` package
- **Express Helpers**: `@modelcontextprotocol/express` package

---

**Document Version**: 2.0  
**Created**: 2025-01-19  
**Last Updated**: 2025-01-19  
**Changes in v2.0**:
- Corrected SDK package names (split packages)
- Added session-based transport management
- Added `NodeStreamableHTTPServerTransport` usage
- Revised time estimates (4 hours → 1-2 days)
- Added official example reference
- Added health endpoint for container checks
