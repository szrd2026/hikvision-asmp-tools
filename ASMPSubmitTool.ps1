# Compatibility launcher. All application logic is implemented in Python.
[CmdletBinding()]
param([switch]$Login, [switch]$SmokeTest)
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run python setup_env.py first, or use the packaged application.' }
$launchArguments = @((Join-Path $PSScriptRoot 'run.py'))
if ($Login) { $launchArguments += '--login' }
if ($SmokeTest) { $launchArguments += '--smoke-test' }
& $pythonPath @launchArguments
exit $LASTEXITCODE
