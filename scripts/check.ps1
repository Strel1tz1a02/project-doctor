$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    uv run --locked pytest
    if ($LASTEXITCODE -ne 0) { throw 'Contract tests failed' }
    uv run --locked ruff check .
    if ($LASTEXITCODE -ne 0) { throw 'Ruff failed' }
    uv run --locked ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw 'Format check failed' }
    uv run --locked mypy
    if ($LASTEXITCODE -ne 0) { throw 'Type check failed' }
} finally {
    Pop-Location
}
