# MCP Server Approach - Using Official Image

## Decision Summary

**We use the official Grafana MCP Server Docker image instead of including the source code in our repository.**

## Rationale

### Why Use Official Image?

✅ **Benefits:**
1. **Official, tested builds** - Grafana maintains and tests these images
2. **No build overhead** - Pull ready-to-use images
3. **Smaller repository** - No Go source code in our repo
4. **Easy version management** - Pin to specific versions or use `latest`
5. **Automatic updates** - Pull new versions when available
6. **Separation of concerns** - We focus on our agent, they maintain the MCP server
7. **Faster deployments** - No compile time needed

❌ **Trade-offs:**
- Cannot modify MCP server code easily (but we shouldn't need to)
- Dependency on Docker Hub / Grafana's registry

## Implementation

### Docker Compose

```yaml
services:
  mcp-server:
    image: grafana/mcp-grafana:latest  # Official image
    environment:
      - GRAFANA_URL=${GRAFANA_URL}
      - GRAFANA_TOKEN=${GRAFANA_TOKEN}
    command: ["--transport", "sse", "--address", "0.0.0.0:8888"]
    ports:
      - "8888:8888"
```

### Standalone Docker

```bash
docker pull grafana/mcp-grafana:latest

docker run -p 8888:8888 \
  -e GRAFANA_URL=https://your-grafana.com \
  -e GRAFANA_TOKEN=your-token \
  grafana/mcp-grafana:latest \
  --transport sse --address 0.0.0.0:8888
```

## Version Pinning

For production, it's recommended to pin to a specific version:

```yaml
services:
  mcp-server:
    image: grafana/mcp-grafana:v1.0.0  # Specific version
```

Check available versions:
- Docker Hub: https://hub.docker.com/r/grafana/mcp-grafana/tags
- GitHub Releases: https://github.com/grafana/mcp-grafana/releases

## Updating

```bash
# Pull latest version
docker pull grafana/mcp-grafana:latest

# Restart services with new image
docker-compose up -d mcp-server

# Or restart everything
docker-compose up -d --force-recreate
```

## For MCP Server Development

If you need to develop or modify the MCP server itself:

1. Clone the official repository:
   ```bash
   git clone https://github.com/grafana/mcp-grafana.git
   cd mcp-grafana
   ```

2. Build locally:
   ```bash
   docker build -t my-mcp-server .
   ```

3. Use your custom image in docker-compose:
   ```yaml
   services:
     mcp-server:
       image: my-mcp-server:latest  # Your custom build
   ```

4. Contribute changes back:
   - Fork the repository
   - Make your changes
   - Submit a pull request to https://github.com/grafana/mcp-grafana

## Project Structure

```
grafana-web-agent/
├── sm3_agent/          # Our Python agent
├── frontend/           # Our React UI
├── docker-compose.yml  # Uses grafana/mcp-grafana:latest
└── .gitignore          # Excludes mcp-grafana/
```

**Note:** The `mcp-grafana/` directory is excluded via `.gitignore`

## References

- Official MCP Server: https://github.com/grafana/mcp-grafana
- Docker Hub Image: https://hub.docker.com/r/grafana/mcp-grafana
- MCP Protocol Spec: https://modelcontextprotocol.io/

## Summary

This approach follows best practices:
- ✅ Use official, maintained images for dependencies
- ✅ Keep our repository focused on our code
- ✅ Easy to update and maintain
- ✅ Clear separation between our agent and the MCP server

We build and maintain:
- Python agent backend (`sm3_agent/`)
- React web UI (`frontend/web/`)
- Integration layer and documentation

Grafana maintains:
- MCP Server (`grafana/mcp-grafana`)
- Protocol implementation
- Grafana API tools
