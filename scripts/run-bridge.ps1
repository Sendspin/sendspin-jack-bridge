<#
.SYNOPSIS
    Launch the Sendspin JACK Bridge.

.DESCRIPTION
    Thin wrapper around the `sendspin-jack-bridge` command with friendly
    defaults. Requires the JACK server (QjackCtl) and a Sendspin server to be
    running first.

    For options beyond server URL and auto-connect (e.g. --name, --channels,
    --bit-depth, --verbose), run `sendspin-jack-bridge` directly — see the
    README's "Command-Line Options" and "Examples".

.PARAMETER Server
    Sendspin server WebSocket URL. Default 'ws://localhost:8927/sendspin'.
    For a server on another machine, use ws://YOUR_SERVER_IP:8927/sendspin.

.PARAMETER Connect
    Optional JACK port pattern to auto-connect on startup, e.g.
    'system:capture_*'. Omit to connect ports manually in QjackCtl.

.EXAMPLE
    .\scripts\run-bridge.ps1

    Connect to a local server and connect JACK ports manually.

.EXAMPLE
    .\scripts\run-bridge.ps1 -Connect "system:capture_*"

    Auto-connect the system capture ports on startup.

.EXAMPLE
    .\scripts\run-bridge.ps1 -Server ws://192.168.1.100:8927/sendspin -Connect "system:capture_*"

    Connect to a remote server and auto-connect the capture ports.
#>
[CmdletBinding()]
param(
    [string]$Server = "ws://localhost:8927/sendspin",
    [string]$Connect
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command sendspin-jack-bridge -ErrorAction SilentlyContinue)) {
    Write-Error "sendspin-jack-bridge was not found on PATH. Run scripts\install.ps1 first."
    exit 1
}

$cliArgs = @("--server", $Server)
if ($Connect) { $cliArgs += @("--connect", $Connect) }

Write-Host "Launching: sendspin-jack-bridge $($cliArgs -join ' ')" -ForegroundColor Cyan
sendspin-jack-bridge @cliArgs
