param(
    [Parameter(Position = 0)]
    [ValidateSet("setup", "test-fast", "frontend-test", "frontend-layout", "eval-agent", "verify")]
    [string]$Task = "verify"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

function Get-ProjectPython {
    $candidates = @(
        (Join-Path $ProjectRoot "venv/Scripts/python.exe"),
        (Join-Path $ProjectRoot "venv/bin/python"),
        "python3",
        "python"
    )
    foreach ($candidate in $candidates) {
        if ((Test-Path -LiteralPath $candidate) -or (Get-Command $candidate -ErrorAction SilentlyContinue)) {
            return $candidate
        }
    }
    throw "Python was not found. Run './scripts/task.ps1 setup' after installing Python 3.11+."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host "`n==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

function Invoke-BackendTests {
    $python = Get-ProjectPython
    if (-not $env:SECRET_KEY) {
        $env:SECRET_KEY = "test-only-harness-secret-key-not-for-production"
    }
    Invoke-Checked "Python tests" { & $python -m pytest -q }
}

function Invoke-AgentEvals {
    $python = Get-ProjectPython
    if (-not $env:SECRET_KEY) {
        $env:SECRET_KEY = "test-only-harness-secret-key-not-for-production"
    }
    Invoke-Checked "Agent behavior evals" { & $python -m pytest -q unit_tests/test_agent_evals.py }
}

function Invoke-FrontendTests {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        throw "Node.js was not found. It is required for frontend regression tests."
    }
    Invoke-Checked "Frontend regression tests" { & node --test unit_tests/frontend_regressions.cjs }
}

switch ($Task) {
    "setup" {
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "venv"))) {
            $bootstrapPython = if (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } else { "python" }
            Invoke-Checked "Create virtual environment" { & $bootstrapPython -m venv venv }
        }
        $python = Get-ProjectPython
        Invoke-Checked "Install development dependencies" { & $python -m pip install -r requirements-dev.txt }
    }
    "test-fast" {
        $python = Get-ProjectPython
        Invoke-Checked "Ruff" { & $python -m ruff check backend unit_tests }
        Invoke-BackendTests
    }
    "frontend-test" { Invoke-FrontendTests }
    "frontend-layout" {
        if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
            throw "Node.js was not found."
        }
        Invoke-Checked "Frontend layout tests" { & node unit_tests/frontend_layout.cjs }
    }
    "eval-agent" { Invoke-AgentEvals }
    "verify" {
        $python = Get-ProjectPython
        Invoke-Checked "Ruff" { & $python -m ruff check backend unit_tests }
        Invoke-Checked "mypy" { & $python -m mypy backend }
        Invoke-BackendTests
        Invoke-FrontendTests
    }
}

Write-Host "`nTask '$Task' completed successfully."
