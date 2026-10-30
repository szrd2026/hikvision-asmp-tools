# ============================================================================
# Build a portable Windows release ZIP and its SHA-256 checksum.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
# ============================================================================
[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version = '1.0.0'
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Dist = Join-Path $Root 'dist'
$PackageName = "Hikvision-ASMP-Submit-v$Version-win64"
$ZipPath = Join-Path $Dist "$PackageName.zip"
$ChecksumPath = Join-Path $Dist 'checksums.txt'
$Stage = Join-Path $env:TEMP ("$PackageName-" + [guid]::NewGuid().ToString('N'))

$RuntimeFiles = @(
    'ASMPSubmitTool.ps1',
    'Start-Submit.bat',
    'submit_config.example.json',
    'README.md',
    'LICENSE',
    'CHANGELOG.md'
)

try {
    New-Item -ItemType Directory -Force -Path $Dist | Out-Null
    New-Item -ItemType Directory -Force -Path $Stage | Out-Null

    foreach ($file in $RuntimeFiles) {
        $source = Join-Path $Root $file
        if (-not (Test-Path $source)) {
            throw "Required file is missing: $file"
        }
        Copy-Item $source -Destination $Stage
    }

    $docs = Join-Path $Root 'docs'
    if (Test-Path $docs) {
        Copy-Item $docs -Destination $Stage -Recurse
    }

    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
    Compress-Archive -Path (Join-Path $Stage '*') -DestinationPath $ZipPath -CompressionLevel Optimal

    $hash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $size = (Get-Item $ZipPath).Length
    "$hash  $PackageName.zip" | Set-Content -Path $ChecksumPath -Encoding ASCII

    [pscustomobject]@{
        Package = $ZipPath
        Bytes = $size
        SHA256 = $hash
        Checksums = $ChecksumPath
    } | Format-List
}
finally {
    if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
}
