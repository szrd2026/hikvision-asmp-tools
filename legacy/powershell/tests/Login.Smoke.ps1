$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$core = Join-Path $root 'lib\Microsoft.Web.WebView2.Core.dll'
$forms = Join-Path $root 'lib\Microsoft.Web.WebView2.WinForms.dll'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -Path $core
Add-Type -Path $forms
[Microsoft.Web.WebView2.Core.CoreWebView2Environment]::SetLoaderDllFolderPath((Join-Path $root 'lib\x64'))
Add-Type -Path (Join-Path $root 'Asmp.Login.cs') -ReferencedAssemblies @('System.dll','System.Drawing.dll','System.Windows.Forms.dll',$core,$forms)
$window = New-Object Asmp.LoginWindow((Join-Path $env:TEMP ('HikvisionAsmp-Smoke-' + [guid]::NewGuid().ToString('N'))))
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 500
$watch = [Diagnostics.Stopwatch]::StartNew()
$script:passed = $false
$timer.Add_Tick({
    if ($window.Ready -and $window.PageTitle) {
        $script:passed = $true
        Write-Output 'BROWSER_SMOKE_OK: official page loaded in InPrivate WebView2'
        $timer.Stop(); $window.Close()
    } elseif ($window.Error -or $watch.Elapsed.TotalSeconds -gt 30) {
        $timer.Stop(); $window.Close()
    }
})
$timer.Start()
try { [void]$window.ShowDialog() }
finally { $timer.Dispose(); $window.Dispose() }
if (-not $script:passed) { throw ('Browser smoke failed: ' + $window.Error) }
Write-Output 'BROWSER_SMOKE_OK: official page loaded in InPrivate WebView2'
