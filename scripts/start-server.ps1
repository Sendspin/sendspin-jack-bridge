<#
.SYNOPSIS
    Start a local Sendspin server for the bridge to connect to.

.DESCRIPTION
    Wraps the README's `python -c "..."` server one-liner in a clean command.
    Starts an aiosendspin SendspinServer and runs it until you press Ctrl+C.
    Run this in its own terminal and leave it open while the bridge is running.

.PARAMETER Port
    TCP port the server listens on. Default 8927.

.PARAMETER ServerId
    Stable identifier for the server. Default 'home'.

.PARAMETER ServerName
    Friendly display name for the server. Default 'Home'.

.EXAMPLE
    .\scripts\start-server.ps1

    Start the server on port 8927 as 'Home'.

.EXAMPLE
    .\scripts\start-server.ps1 -Port 9000 -ServerName "Studio"

    Start the server on port 9000 with a custom name.
#>
[CmdletBinding()]
param(
    [int]$Port = 8927,
    [string]$ServerId = "home",
    [string]$ServerName = "Home"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python was not found on PATH. Run scripts\install.ps1 first."
    exit 1
}

# Equivalent to the README one-liner, parameterized. python -c accepts a
# multi-line program; the here-string keeps each statement at column 0.
$code = @"
import asyncio
from aiosendspin.server.server import SendspinServer
loop = asyncio.new_event_loop()
server = SendspinServer(loop=loop, server_id='$ServerId', server_name='$ServerName')
loop.run_until_complete(server.start_server(port=$Port))
print('Sendspin server running on port $Port - press Ctrl+C to stop')
loop.run_forever()
"@

Write-Host "Starting Sendspin server '$ServerName' (id '$ServerId') on port $Port..." -ForegroundColor Cyan
python -c $code
