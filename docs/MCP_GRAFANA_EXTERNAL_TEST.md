# Testing MCP Grafana Against External Instance

This setup allows you to test the MCP Grafana server locally against an external Grafana instance.

## Configuration

- **External Grafana URL**: https://maas-1203.mon.sabio.cloud (10.10.42.4)
- **Authentication**: Service Account Token
- **MCP Server Mode**: SSE (Server-Sent Events) on port 8000
- **Docker**: Local build from `mcp-grafana` directory

## Files

- `docker-compose.mcp-test.yml` - Docker Compose configuration for MCP server
- `.env.mcp-test` - Environment variables (includes Grafana URL and token)
- `test-mcp-grafana.ps1` - PowerShell script for managing the test server

## Quick Start

### 1. Build and Start the MCP Server

```powershell
# Build the Docker image
.\test-mcp-grafana.ps1 -Build

# Start the server
.\test-mcp-grafana.ps1
```

### 2. Test the Connection

```powershell
# Test the MCP server endpoint
.\test-mcp-grafana.ps1 -Test
```

### 3. View Logs

```powershell
# View server logs
.\test-mcp-grafana.ps1 -Logs
```

### 4. Stop the Server

```powershell
# Stop the server
.\test-mcp-grafana.ps1 -Stop
```

## MCP Server Endpoints

Once running, the MCP server will be available at:

- **SSE Endpoint**: http://localhost:8001/sse
- **Base URL**: http://localhost:8001

## Integration with Claude Desktop

To use this MCP server with Claude Desktop, add this to your Claude config file (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "grafana-external": {
      "type": "sse",
      "url": "http://localhost:8000/sse"
    }
  }
}
```

## Integration with VSCode

To use this MCP server with VSCode, add this to `.vscode/settings.json`:

```json
{
  "mcp": {
    "servers": {
      "grafana-external": {
        "type": "sse",
        "url": "http://localhost:8000/sse"
      }
    }
  }
}
```

## Manual Docker Commands

If you prefer to run Docker commands directly:

```powershell
# Build the image
docker-compose -f docker-compose.mcp-test.yml --env-file .env.mcp-test build

# Start the server
docker-compose -f docker-compose.mcp-test.yml --env-file .env.mcp-test up -d

# View logs
docker-compose -f docker-compose.mcp-test.yml --env-file .env.mcp-test logs -f

# Stop the server
docker-compose -f docker-compose.mcp-test.yml --env-file .env.mcp-test down
```

## Testing MCP Tools

Once the server is running, you can test various MCP tools through your MCP client:

### List Datasources
```
list_datasources
```

### Search Dashboards
```
search_dashboards with query "monitoring"
```

### Get Dashboard Summary
```
get_dashboard_summary with uid "<dashboard-uid>"
```

### Query Prometheus
```
query_prometheus with datasource_uid "<prometheus-uid>" and query "up"
```

## Troubleshooting

### Connection Issues

If you can't connect to the MCP server:

1. Check if the container is running:
   ```powershell
   docker ps | Select-String "mcp-grafana-test"
   ```

2. Check the logs:
   ```powershell
   .\test-mcp-grafana.ps1 -Logs
   ```

3. Verify the port is accessible:
   ```powershell
   Test-NetConnection -ComputerName localhost -Port 8000
   ```

### Grafana Authentication Issues

If you see authentication errors:

1. Verify the token is correct in `.env.mcp-test`
2. Check token permissions in Grafana
3. Ensure the token has the necessary RBAC scopes

### Network Issues

If the MCP server can't reach Grafana:

1. Verify the Grafana URL is accessible from your machine:
   ```powershell
   curl https://maas-1203.mon.sabio.cloud
   ```

2. Check for any firewall or proxy issues

## Security Notes

- The `.env.mcp-test` file contains sensitive credentials
- This file should be added to `.gitignore` to prevent accidental commits
- Consider using a read-only service account token for testing
- The MCP server runs on localhost and is only accessible from your machine

## Available MCP Tools

The MCP server provides these tool categories:

- **Search**: Search for dashboards and resources
- **Dashboards**: Get, update, and manage dashboards
- **Datasources**: List and query datasources
- **Prometheus**: Query metrics and metadata
- **Loki**: Query logs and metadata
- **Alerting**: View alert rules and contact points
- **OnCall**: Manage on-call schedules and users
- **Sift**: Investigate logs and traces
- **Incidents**: Manage Grafana incidents
- **Navigation**: Generate deeplinks to Grafana resources
- **Annotations**: Create and manage annotations

To disable specific tool categories, modify the docker-compose file to add command-line flags like `--disable-write` or `--disable-oncall`.
