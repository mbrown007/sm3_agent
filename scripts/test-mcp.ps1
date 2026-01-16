# Test MCP Server directly on Windows
# This script tests dashboard queries against the MCP server

$MCP_URL = "http://localhost:8888/mcp"
$UID = "gvmbnk"

Write-Host "=== Testing MCP Server ===" -ForegroundColor Cyan
Write-Host "MCP URL: $MCP_URL"
Write-Host ""

# Test 1: Search dashboards
Write-Host "Test 1: search_dashboards" -ForegroundColor Yellow
$searchPayload = @{
    jsonrpc = "2.0"
    id = 1
    method = "tools/call"
    params = @{
        name = "search_dashboards"
        arguments = @{
            query = "test"
        }
    }
} | ConvertTo-Json

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
    Write-Host "Response: $($_.Exception.Response.Content)" -ForegroundColor Red
}

Write-Host ""
Write-Host ""

# Test 2: Get dashboard summary with gvmbnk UID
Write-Host "Test 2: get_dashboard_summary (uid: $UID)" -ForegroundColor Yellow
$summaryPayload = @{
    jsonrpc = "2.0"
    id = 2
    method = "tools/call"
    params = @{
        name = "get_dashboard_summary"
        arguments = @{
            uid = $UID
        }
    }
} | ConvertTo-Json

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
    Write-Host "Full Response:" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $reader.BaseStream.Position = 0
        $reader.DiscardBufferedData()
        Write-Host $reader.ReadToEnd()
    }
}

Write-Host ""
Write-Host ""

# Test 3: Get dashboard by UID (for comparison)
Write-Host "Test 3: get_dashboard_by_uid (uid: $UID)" -ForegroundColor Yellow
$fullPayload = @{
    jsonrpc = "2.0"
    id = 3
    method = "tools/call"
    params = @{
        name = "get_dashboard_by_uid"
        arguments = @{
            uid = $UID
        }
    }
} | ConvertTo-Json

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
    Write-Host "Full Response:" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $reader.BaseStream.Position = 0
        $reader.DiscardBufferedData()
        Write-Host $reader.ReadToEnd()
    }
}

Write-Host ""
Write-Host "=== Tests Complete ===" -ForegroundColor Cyan
