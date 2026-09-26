# Simple PowerShell HTTP Server
# Run this with: .\Start-Server.ps1

$port = 8000
$url = "http://localhost:$port"

# Get script directory (fallback to current directory if running interactively)
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Get-Location }

Write-Host "Starting HTTP Server on $url" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

# Start simple HTTP server using .NET
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("$url/")
$listener.Start()

try {
    Write-Host "Server running! Visit: $url" -ForegroundColor Cyan
    Write-Host ""
    
    while ($listener.IsListening) {
        $context = $null
        try {
            $context = $listener.GetContext()
            $request = $context.Request
            $response = $context.Response
            
            $path = $request.Url.LocalPath
            if ($path -eq "/") { $path = "/index.html" }
            
            $filePath = Join-Path $scriptDir $path.TrimStart('/')
            
            if (Test-Path $filePath) {
                $content = [System.IO.File]::ReadAllBytes($filePath)
                
                # Set content type
                $ext = [System.IO.Path]::GetExtension($filePath)
                $contentType = switch ($ext) {
                    ".html" { "text/html; charset=utf-8" }
                    ".js" { "application/javascript; charset=utf-8" }
                    ".css" { "text/css; charset=utf-8" }
                    ".json" { "application/json; charset=utf-8" }
                    default { "application/octet-stream" }
                }
                
                $response.ContentType = $contentType
                $response.ContentLength64 = $content.Length
                $response.OutputStream.Write($content, 0, $content.Length)
            }
            else {
                $response.StatusCode = 404
                $buffer = [System.Text.Encoding]::UTF8.GetBytes("404 - Not Found")
                $response.ContentLength64 = $buffer.Length
                $response.OutputStream.Write($buffer, 0, $buffer.Length)
            }
            
            $response.Close()
            Write-Host "$($request.HttpMethod) $($request.Url.LocalPath) - $($response.StatusCode)" -ForegroundColor Gray
        }
        catch {
            Write-Host "Error handling request: $_" -ForegroundColor Red
            if ($context -and $context.Response) {
                try { $context.Response.Close() } catch {}
            }
        }
    }
}
finally {
    $listener.Stop()
    $listener.Close()
}
