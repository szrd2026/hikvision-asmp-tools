# Compatibility launcher for the cross-platform Python builder.
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create .venv and install requirements-dev.txt first.' }
& $pythonPath (Join-Path $PSScriptRoot 'tools\build.py') @args
exit $LASTEXITCODE
