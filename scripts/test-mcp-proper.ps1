# Test MCP Server with proper session initialization on Windows
# This script tests dashboard queries against the MCP server with correct MCP protocol

$MCP_URL = "http://localhost:8888/mcp"
$UID = "gvmbnk"

Write-Host "=== Testing MCP Server with Session Init ===" -ForegroundColor Cyan
Write-Host "MCP URL: $MCP_URL"
Write-Host ""

# Step 1: Initialize the MCP session
Write-Host "Step 1: Initializing MCP session" -ForegroundColor Yellow

$initPayload = @{
    jsonrpc = "2.0"
    id = 0
    method = "initialize"
    params = @{
        protocolVersion = "2024-11-05"
        capabilities = @{}
        clientInfo = @{
            name = "test-client"
            version = "1.0"
        }
    }
} | ConvertTo-Json -Depth 10

Write-Host "Init Request:" -ForegroundColor Gray
Write-Host $initPayload
Write-Host ""

try {
    $initResponse = Invoke-WebRequest -Uri $MCP_URL `
        -Method POST `
        -ContentType "application/json" `
        -Body $initPayload `
        -ErrorAction Stop
    
    Write-Host "Init Response Status: $($initResponse.StatusCode)" -ForegroundColor Green
    $initBody = $initResponse.Content | ConvertFrom-Json
    Write-Host "Init Response:" -ForegroundColor Gray
    Write-Host ($initBody | ConvertTo-Json -Depth 5)
} catch {
    Write-Host "Init Error: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $reader.BaseStream.Position = 0
        $reader.DiscardBufferedData()
        Write-Host $reader.ReadToEnd()
    }
    exit 1
}

Write-Host ""
Write-Host ""

# Step 2: List available tools
Write-Host "Step 2: Listing available tools" -ForegroundColor Yellow

$listPayload = @{
    jsonrpc = "2.0"
    id = 1
    method = "tools/list"
} | ConvertTo-Json

try {
    $listResponse = Invoke-WebRequest -Uri $MCP_URL `
        -Method POST `
        -ContentType "application/json" `
        -Body $listPayload `
        -ErrorAction Stop
    
    Write-Host "Tools Response Status: $($listResponse.StatusCode)" -ForegroundColor Green
    $listBody = $listResponse.Content | ConvertFrom-Json
    Write-Host "Available Tools:" -ForegroundColor Gray
    if ($listBody.result.tools) {
        $listBody.result.tools | ForEach-Object { Write-Host "  - $($_.name)" }
    }
} catch {
    Write-Host "List Error: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host ""

# Step 3: Search dashboards
Write-Host "Step 3: search_dashboards" -ForegroundColor Yellow
$searchPayload = @{
    jsonrpc = "2.0"
    id = 2
    method = "tools/call"
    params = @{
        name = "search_dashboards"
        arguments = @{
            query = "test"
        }
    }
} | ConvertTo-Json -Depth 10

Write-Host "Request:" -ForegroundColor Gray
Write-Host $searchPayload
Write-Host ""

try {
    $response = Invoke-WebRequest -Uri $MCP_URL `
        -Method POST `
        -ContentType "application/json" `
        -Body $searchPayload `
        -ErrorAction Stop
    
    Write-Host "Response Status: $($response.StatusCode)" -ForegroundColor Green
    Write-Host "Response Body:" -ForegroundColor Gray
    $response.Content | ConvertFrom-Json | ConvertTo-Json -Depth 10
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $reader.BaseStream.Position = 0
        $reader.DiscardBufferedData()
        Write-Host $reader.ReadToEnd()
    }
}

Write-Host ""
Write-Host ""

# Step 4: Get dashboard summary with gvmbnk UID
Write-Host "Step 4: get_dashboard_summary (uid: $UID)" -ForegroundColor Yellow
$summaryPayload = @{
    jsonrpc = "2.0"
    id = 3
    method = "tools/call"
    params = @{
        name = "get_dashboard_summary"
        arguments = @{
            uid = $UID
        }
    }
} | ConvertTo-Json -Depth 10

Write-Host "Request:" -ForegroundColor Gray
Write-Host $summaryPayload
Write-Host ""

try {
    $response = Invoke-WebRequest -Uri $MCP_URL `
        -Method POST `
        -ContentType "application/json" `
        -Body $summaryPayload `
        -ErrorAction Stop
    
    Write-Host "Response Status: $($response.StatusCode)" -ForegroundColor Green
    Write-Host "Response Body:" -ForegroundColor Gray
    $response.Content | ConvertFrom-Json | ConvertTo-Json -Depth 10
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $reader.BaseStream.Position = 0
        $reader.DiscardBufferedData()
        Write-Host $reader.ReadToEnd()
    }
}

Write-Host ""
Write-Host ""

# Step 5: Get dashboard by UID (for comparison)
Write-Host "Step 5: get_dashboard_by_uid (uid: $UID)" -ForegroundColor Yellow
$fullPayload = @{
    jsonrpc = "2.0"
    id = 4
    method = "tools/call"
    params = @{
        name = "get_dashboard_by_uid"
        arguments = @{
            uid = $UID
        }
    }
} | ConvertTo-Json -Depth 10

Write-Host "Request:" -ForegroundColor Gray
Write-Host $fullPayload
Write-Host ""

try {
    $response = Invoke-WebRequest -Uri $MCP_URL `
        -Method POST `
        -ContentType "application/json" `
        -Body $fullPayload `
        -ErrorAction Stop
    
    Write-Host "Response Status: $($response.StatusCode)" -ForegroundColor Green
    Write-Host "Response Body (truncated):" -ForegroundColor Gray
    $json = $response.Content | ConvertFrom-Json
    Write-Host ($json | ConvertTo-Json -Depth 3)
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $reader.BaseStream.Position = 0
        $reader.DiscardBufferedData()
        Write-Host $reader.ReadToEnd()
    }
}

Write-Host ""
Write-Host "=== Tests Complete ===" -ForegroundColor Cyan
