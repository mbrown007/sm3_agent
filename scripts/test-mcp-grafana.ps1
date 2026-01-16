# Test script for MCP Grafana against external instance
# This script builds and runs the MCP server in SSE mode for testing

param(
    [switch]$Build,
    [switch]$Stop,
    [switch]$Logs,
    [switch]$Test
)

$ErrorActionPreference = "Stop"

$dockerComposeFile = "docker-compose.mcp-test.yml"
$envFile = ".env.mcp-test"

if ($Stop) {
    Write-Host "Stopping MCP Grafana test containers..." -ForegroundColor Yellow
    docker-compose -f $dockerComposeFile --env-file $envFile down
    exit 0
}

if ($Build) {
    Write-Host "Building MCP Grafana Docker image..." -ForegroundColor Cyan
    docker-compose -f $dockerComposeFile --env-file $envFile build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Build failed!" -ForegroundColor Red
        exit 1
    }
    Write-Host "Build completed successfully!" -ForegroundColor Green
}

if ($Logs) {
    Write-Host "Showing logs for MCP Grafana..." -ForegroundColor Cyan
    docker-compose -f $dockerComposeFile --env-file $envFile logs -f
    exit 0
}

Write-Host "Starting MCP Grafana test server..." -ForegroundColor Cyan
docker-compose -f $dockerComposeFile --env-file $envFile up -d

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nMCP Grafana server started successfully!" -ForegroundColor Green
    Write-Host "`nServer is running in SSE mode on: http://localhost:8001" -ForegroundColor Cyan
    Write-Host "SSE endpoint: http://localhost:8001/sse" -ForegroundColor Cyan
    Write-Host "`nGrafana instance: https://maas-1203.mon.sabio.cloud" -ForegroundColor Yellow
    Write-Host "`nCommands:" -ForegroundColor White
    Write-Host "  .\test-mcp-grafana.ps1 -Logs    # View logs" -ForegroundColor Gray
    Write-Host "  .\test-mcp-grafana.ps1 -Stop    # Stop the server" -ForegroundColor Gray
    Write-Host "  .\test-mcp-grafana.ps1 -Test    # Test the connection" -ForegroundColor Gray
    Write-Host "  .\test-mcp-grafana.ps1 -Build   # Rebuild the image" -ForegroundColor Gray
}

if ($Test) {
    Write-Host "`nTesting MCP server connection..." -ForegroundColor Cyan
    Start-Sleep -Seconds 2
    
    # Check if container is running
    Write-Host "Checking container status..." -ForegroundColor Yellow
    $container = docker ps --filter "name=mcp-grafana-test" --format "{{.Status}}"
    if ($container) {
        Write-Host "Container is running: $container" -ForegroundColor Green
    } else {
        Write-Host "Container is not running!" -ForegroundColor Red
        exit 1
    }
    
    # Check port is listening
    Write-Host "Checking if port 8001 is listening..." -ForegroundColor Yellow
    $portTest = Test-NetConnection -ComputerName localhost -Port 8001 -WarningAction SilentlyContinue
    if ($portTest.TcpTestSucceeded) {
        Write-Host "Port 8001 is accessible" -ForegroundColor Green
        Write-Host "`nMCP Server is ready!" -ForegroundColor Green
        Write-Host "SSE endpoint: http://localhost:8001/sse" -ForegroundColor Cyan
    } else {
        Write-Host "Port 8001 is not accessible" -ForegroundColor Red
        Write-Host "Check logs with: .\test-mcp-grafana.ps1 -Logs" -ForegroundColor Yellow
    }
}
