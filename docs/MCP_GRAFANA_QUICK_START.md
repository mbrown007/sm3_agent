# MCP Grafana External Instance - Quick Start

## ✅ Server Status: RUNNING

- **MCP Server**: http://localhost:8001
- **SSE Endpoint**: http://localhost:8001/sse
- **Target Grafana**: https://maas-1203.mon.sabio.cloud (10.10.42.4)
- **Container**: mcp-grafana-test

## Quick Commands

```powershell
# View logs
.\test-mcp-grafana.ps1 -Logs

# Stop server
.\test-mcp-grafana.ps1 -Stop

# Restart server
.\test-mcp-grafana.ps1

# Test connection
.\test-mcp-grafana.ps1 -Test

# Rebuild image
.\test-mcp-grafana.ps1 -Build
```

## Integration Examples

### For Claude Desktop

Add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "grafana-external": {
      "type": "sse",
      "url": "http://localhost:8001/sse"
    }
  }
}
```

### For VSCode

Add to `.vscode/settings.json`:

```json
{
  "mcp": {
    "servers": {
      "grafana-external": {
        "type": "sse",
        "url": "http://localhost:8001/sse"
      }
    }
  }
}
```

## Test Queries

Once connected through your MCP client, try:

```
# List all datasources
list_datasources

# Search for dashboards
search_dashboards

# List alert rules
list_alert_rules

# List contact points
list_contact_points
```

## Files

- `docker-compose.mcp-test.yml` - Docker config
- `.env.mcp-test` - Credentials (contains service account token)
- `test-mcp-grafana.ps1` - Management script
- `MCP_GRAFANA_EXTERNAL_TEST.md` - Full documentation

## Security Note

⚠️ The `.env.mcp-test` file contains your service account token. Keep it secure and don't commit it to git.
