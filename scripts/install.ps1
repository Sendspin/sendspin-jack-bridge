<#
.SYNOPSIS
    One-time setup for the Sendspin JACK Bridge on Windows.

.DESCRIPTION
    Verifies prerequisites (Python 3.12+, git on PATH; warns if the JACK
    runtime is not detected), clones the aiosendspin library as a sibling of
    this repository on its source-v1 branch, then installs aiosendspin followed
    by this bridge with pip. Safe to re-run: an existing aiosendspin clone is
    fetched and refreshed rather than re-cloned.

    The bridge itself is NOT cloned — this script ships inside it, so it only
    runs `pip install .` for the current repository.

.PARAMETER AiosendspinRepo
    Git URL for the aiosendspin library. Defaults to the upstream Sendspin repo.

.EXAMPLE
    .\scripts\install.ps1

    Run the full one-time setup from the repository root.

.NOTES
    This automates Step 4 of the README. The GUI prerequisites (installing
    Python, installing JACK2 + reboot, and configuring QjackCtl) are NOT
    scripted and must be completed first — see the README.
#>
[CmdletBinding()]
param(
    [string]$AiosendspinRepo = "https://github.com/Sendspin/aiosendspin.git"
)

$ErrorActionPreference = "Stop"

function Fail($message) {
    Write-Error $message
    exit 1
}

# Resolve paths: <parent>/sendspin-jack-bridge (this repo) and <parent>/aiosendspin.
$repoRoot = Split-Path -Parent $PSScriptRoot
$parentDir = Split-Path -Parent $repoRoot
$aiosendspinPath = Join-Path $parentDir "aiosendspin"

Write-Host "== Sendspin JACK Bridge setup ==" -ForegroundColor Cyan
Write-Host "Bridge repo:  $repoRoot"
Write-Host "aiosendspin:  $aiosendspinPath"
Write-Host ""

# --- Prerequisite: Python 3.12+ ---
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "Python was not found on PATH. Install Python 3.12+ from https://www.python.org/downloads/ (check 'Add Python to PATH'), then re-run this script."
}

$pythonVersionRaw = (& python --version 2>&1) -join " "
if ($pythonVersionRaw -notmatch "Python (\d+)\.(\d+)") {
    Fail "Could not determine the Python version (got '$pythonVersionRaw'). Ensure 'python --version' reports Python 3.12 or later."
}
$pyMajor = [int]$Matches[1]
$pyMinor = [int]$Matches[2]
if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 12)) {
    Fail "Python 3.12+ is required, but found $pythonVersionRaw. Install a newer Python from https://www.python.org/downloads/."
}
Write-Host "[ok] $pythonVersionRaw" -ForegroundColor Green

# --- Prerequisite: git ---
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "git was not found on PATH. Install Git for Windows from https://git-scm.com/download/win, then re-run this script."
}
Write-Host "[ok] git found" -ForegroundColor Green

# --- Soft check: JACK runtime ---
$jackFound = $false
if (Get-Command jackd -ErrorAction SilentlyContinue) { $jackFound = $true }
if (-not $jackFound) {
    foreach ($dir in @($env:windir, (Join-Path $env:ProgramFiles "JACK2"), (Join-Path ${env:ProgramFiles(x86)} "JACK2"))) {
        if ($dir -and (Test-Path (Join-Path $dir "libjack64.dll"))) { $jackFound = $true; break }
    }
}
if ($jackFound) {
    Write-Host "[ok] JACK runtime detected" -ForegroundColor Green
} else {
    Write-Warning "JACK runtime not detected. Install JACK2 (64-bit) from https://jackaudio.org/downloads/ and reboot before running the bridge. Continuing with package install."
}

# --- Clone / refresh aiosendspin (sibling, source-v1 branch) ---
Write-Host ""
if (Test-Path (Join-Path $aiosendspinPath ".git")) {
    Write-Host "Refreshing existing aiosendspin clone..." -ForegroundColor Cyan
    git -C $aiosendspinPath fetch origin
    if ($LASTEXITCODE -ne 0) { Fail "git fetch failed in $aiosendspinPath." }
} else {
    if (Test-Path $aiosendspinPath) {
        Fail "$aiosendspinPath exists but is not a git clone. Remove or rename it, then re-run."
    }
    Write-Host "Cloning aiosendspin into $aiosendspinPath..." -ForegroundColor Cyan
    git clone $AiosendspinRepo $aiosendspinPath
    if ($LASTEXITCODE -ne 0) { Fail "git clone of $AiosendspinRepo failed." }
}

git -C $aiosendspinPath checkout source-v1
if ($LASTEXITCODE -ne 0) { Fail "Could not check out the 'source-v1' branch in $aiosendspinPath." }

# --- Install packages: aiosendspin first, then this bridge ---
Write-Host ""
Write-Host "Installing aiosendspin..." -ForegroundColor Cyan
python -m pip install $aiosendspinPath
if ($LASTEXITCODE -ne 0) { Fail "pip install of aiosendspin failed." }

Write-Host "Installing sendspin-jack-bridge..." -ForegroundColor Cyan
python -m pip install $repoRoot
if ($LASTEXITCODE -ne 0) { Fail "pip install of sendspin-jack-bridge failed." }

# --- Confirm success ---
Write-Host ""
if (-not (Get-Command sendspin-jack-bridge -ErrorAction SilentlyContinue)) {
    Fail "Install finished but 'sendspin-jack-bridge' is not on PATH. Add your Python Scripts directory to PATH, then re-run."
}

# `sendspin-jack-bridge --help` imports the JACK library, which loads the JACK
# DLLs at import time. Only treat its failure as fatal when JACK is present;
# otherwise the missing runtime (already warned about) would mask a good install.
& sendspin-jack-bridge --help | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[ok] sendspin-jack-bridge runs" -ForegroundColor Green
} elseif ($jackFound) {
    Fail "'sendspin-jack-bridge --help' failed even though JACK was detected. Review the pip install output above."
} else {
    Write-Warning "'sendspin-jack-bridge --help' could not run yet — expected until the JACK runtime is installed (see the warning above). The packages installed successfully."
}

Write-Host "== Setup complete ==" -ForegroundColor Green
Write-Host "Next: start the server (scripts\start-server.ps1) and run the bridge (scripts\run-bridge.ps1)."
