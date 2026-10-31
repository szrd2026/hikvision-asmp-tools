# ASMP v1.1: official-page sign-in, durable submission journal, responsive UI.
[CmdletBinding()]
param([switch]$Login, [switch]$SmokeTest)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -eq 'Core') { throw '请使用 Start-Submit.bat，以 Windows PowerShell 5.1 启动。' }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
. (Join-Path $PSScriptRoot 'Asmp.Core.ps1')
$script:PumpUi = $true
$script:CfgPath = Join-Path $PSScriptRoot 'submit_config.json'
$script:LogDir = Join-Path $PSScriptRoot 'logs'
$script:LogPath = $null
$script:Busy = $false
$script:CurrentToken = ''
$script:ProfileDirectory = Join-Path ([IO.Path]::GetTempPath()) ('HikvisionAsmp-' + [guid]::NewGuid().ToString('N'))

# One writer per installation prevents two processes racing past the duplicate guard.
$sha = [Security.Cryptography.SHA256]::Create()
try { $key = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($PSScriptRoot.ToUpperInvariant()))).Replace('-', '') }
finally { $sha.Dispose() }
$created = $false
$script:Mutex = New-Object Threading.Mutex($true, ('Local\HikvisionAsmp-' + $key), [ref]$created)
if (-not $created) {
    [void][System.Windows.Forms.MessageBox]::Show('此目录的工具已在运行，请使用已打开的窗口。', 'ASMP')
    $script:Mutex.Dispose()
    return
}

function Write-Log([string]$Msg) {
    if ($script:CurrentToken) { $Msg = $Msg.Replace($script:CurrentToken, '[令牌已隐藏]') }
    $line = '[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss'), $Msg
    if ($script:txtLog -and -not $script:txtLog.IsDisposed) {
        $script:txtLog.AppendText($line + "`r`n")
        $script:txtLog.SelectionStart = $script:txtLog.TextLength
        $script:txtLog.ScrollToCaret()
    }
    if ($script:LogPath) { [IO.File]::AppendAllText($script:LogPath, $line + "`r`n", [Text.Encoding]::UTF8) }
}

function Save-Config {
    $cfg = [ordered]@{
        repairClient = $txtRepairClient.Text.Trim(); linkman = $txtLinkman.Text.Trim()
        linknumber = $txtLinknumber.Text.Trim(); rebackFault = $txtFault.Text.Trim()
        rebackFaulttext = $txtFaultText.Text.Trim(); dealType = $txtDealType.Text.Trim()
        repairMode = $txtRepairMode.Text.Trim(); delay = $txtDelay.Text.Trim(); skip = [bool]$chkSkip.Checked
    }
    $temp = $script:CfgPath + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($temp, ($cfg | ConvertTo-Json), (New-Object Text.UTF8Encoding($true)))
    if (Test-Path -LiteralPath $script:CfgPath) { [IO.File]::Replace($temp, $script:CfgPath, [NullString]::Value) }
    else { [IO.File]::Move($temp, $script:CfgPath) }
}

function Load-Config {
    if (-not (Test-Path -LiteralPath $script:CfgPath)) { return }
    try {
        $cfg = Get-Content -LiteralPath $script:CfgPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
        foreach ($pair in @(@('repairClient',$txtRepairClient), @('linkman',$txtLinkman), @('linknumber',$txtLinknumber),
            @('rebackFault',$txtFault), @('rebackFaulttext',$txtFaultText), @('dealType',$txtDealType),
            @('repairMode',$txtRepairMode), @('delay',$txtDelay))) {
            if ($cfg.PSObject.Properties.Name -contains $pair[0]) { $pair[1].Text = [string]$cfg.($pair[0]) }
        }
        if ($cfg.PSObject.Properties.Name -contains 'skip') { $chkSkip.Checked = [bool]$cfg.skip }
        if ($cfg.token) {
            $txtToken.Text = [string]$cfg.token
            $script:CurrentToken = $txtToken.Text
            Save-Config
            Write-Log '已迁移旧配置：移除明文 token，令牌仅在本次会话使用。'
        }
    } catch { Write-Log ('配置读取/迁移失败：' + $_.Exception.Message) }
}

function Set-Busy([bool]$Busy) {
    $script:Busy = $Busy
    $btnStart.Enabled = -not $Busy; $btnLogin.Enabled = -not $Busy; $btnCheck.Enabled = -not $Busy
    $txtToken.Enabled = -not $Busy; $panelFixed.Enabled = -not $Busy; $txtSerials.Enabled = -not $Busy
    $btnStop.Enabled = $Busy
}

function Test-Login([string]$Token) {
    if ([string]::IsNullOrWhiteSpace($Token)) { throw '请先登录或粘贴令牌' }
    $script:CurrentToken = $Token
    $result = Get-AsmpResponse (Invoke-RmaPost "$script:ApiBase/base/getLoginInfo" $Token '{}')
    if (-not $result.Success -or -not $result.Object.data.currentUser) {
        if ($result.AuthExpired) { $txtToken.Clear() }
        throw ('登录检查失败：' + $result.Message)
    }
    $script:LoginInfo = $result.Object.data
    Write-Log '登录检查通过。'
    $lblStatus.Text = '登录有效，可开始提交'
    # Only a boolean status is written for the user-assisted integration check.
    if ($Login) {
        New-Item -ItemType Directory -Path $script:LogDir -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $script:LogDir 'login-check.json'), '{"authenticated":true}', [Text.Encoding]::UTF8)
    }
    return $true
}

function Initialize-LoginLibrary {
    if ('Asmp.LoginWindow' -as [type]) { return }
    $core = Join-Path $PSScriptRoot 'lib\Microsoft.Web.WebView2.Core.dll'
    $forms = Join-Path $PSScriptRoot 'lib\Microsoft.Web.WebView2.WinForms.dll'
    Add-Type -Path $core
    Add-Type -Path $forms
    $arch = $(if ([IntPtr]::Size -eq 8) { 'x64' } else { 'x86' })
    [Microsoft.Web.WebView2.Core.CoreWebView2Environment]::SetLoaderDllFolderPath((Join-Path $PSScriptRoot "lib\$arch"))
    Add-Type -Path (Join-Path $PSScriptRoot 'Asmp.Login.cs') -ReferencedAssemblies @('System.dll', 'System.Drawing.dll', 'System.Windows.Forms.dll', $core, $forms)
}

function Show-OfficialLogin {
    Initialize-LoginLibrary
    if ($Login) {
        New-Item -ItemType Directory -Path $script:LogDir -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $script:LogDir 'login-check.json'), '{"authenticated":false,"state":"awaiting_user"}', [Text.Encoding]::UTF8)
    }
    $window = New-Object Asmp.LoginWindow($script:ProfileDirectory)
    try {
        if ($window.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK -and $window.Token) {
            $txtToken.Text = $window.Token
            [void](Test-Login $window.Token)
        } elseif ($window.Error) { throw $window.Error }
        else { Write-Log '已取消登录。' }
    } finally { $window.Dispose() }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = '海康威视 ASMP 自动提交工具 v1.1'
$form.ClientSize = New-Object System.Drawing.Size(970, 650)
$form.MinimumSize = $form.Size
$form.MaximizeBox = $false
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object System.Drawing.Font('Microsoft YaHei', 9)

$lblToken = New-Object System.Windows.Forms.Label
$lblToken.Text = '登录令牌（可点右侧官方登录自动获取，也可手动粘贴；仅本次会话使用）:'
$lblToken.Location = New-Object System.Drawing.Point(14, 10)
$lblToken.AutoSize = $true
$txtToken = New-Object System.Windows.Forms.TextBox
$txtToken.Location = New-Object System.Drawing.Point(14, 35)
$txtToken.Size = New-Object System.Drawing.Size(720, 24)
$txtToken.UseSystemPasswordChar = $true
$btnLogin = New-Object System.Windows.Forms.Button
$btnLogin.Text = '官方网页登录'
$btnLogin.Location = New-Object System.Drawing.Point(746, 32)
$btnLogin.Size = New-Object System.Drawing.Size(110, 30)
$btnCheck = New-Object System.Windows.Forms.Button
$btnCheck.Text = '检查登录'
$btnCheck.Location = New-Object System.Drawing.Point(862, 32)
$btnCheck.Size = New-Object System.Drawing.Size(88, 30)

$panelFixed = New-Object System.Windows.Forms.FlowLayoutPanel
$panelFixed.Location = New-Object System.Drawing.Point(14, 68)
$panelFixed.Size = New-Object System.Drawing.Size(936, 86)
$panelFixed.FlowDirection = 'LeftToRight'
$panelFixed.WrapContents = $true
$panelFixed.AutoScroll = $true
function New-Field([string]$Label, [int]$Width, [string]$Default) {
    $p = New-Object System.Windows.Forms.Panel
    $p.Size = New-Object System.Drawing.Size(($Width + 85), 28)
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $Label; $l.AutoSize = $true
    $l.Location = New-Object System.Drawing.Point(0, 4)
    $t = New-Object System.Windows.Forms.TextBox
    $t.Text = $Default
    $t.Location = New-Object System.Drawing.Point(($l.PreferredWidth + 4), 1)
    $t.Size = New-Object System.Drawing.Size($Width, 24)
    $p.Controls.AddRange(@($l, $t))
    $panelFixed.Controls.Add($p)
    return ,$t
}
$txtRepairClient = New-Field '送修客户:' 95 ''
$txtLinkman = New-Field '联系人:' 65 ''
$txtLinknumber = New-Field '电话:' 100 ''
$txtFault = New-Field '故障类型:' 65 '其他'
$txtFaultText = New-Field '故障描述:' 245 ''
$txtDealType = New-Field '处理方式:' 40 '2'
$txtRepairMode = New-Field '接修方式:' 40 '2'
$txtDelay = New-Field '间隔毫秒:' 60 '500'
$chkSkip = New-Object System.Windows.Forms.CheckBox
$chkSkip.Text = '跳过已成功提交的序列号'
$chkSkip.Checked = $true; $chkSkip.AutoSize = $true
$panelFixed.Controls.Add($chkSkip)

$lblSerials = New-Object System.Windows.Forms.Label
$lblSerials.Text = '序列号（从 Excel 复制，每行一个；自动去重）:'
$lblSerials.Location = New-Object System.Drawing.Point(14, 160)
$lblSerials.AutoSize = $true
$txtSerials = New-Object System.Windows.Forms.TextBox
$txtSerials.Multiline = $true; $txtSerials.ScrollBars = 'Vertical'
$txtSerials.Location = New-Object System.Drawing.Point(14, 186)
$txtSerials.Size = New-Object System.Drawing.Size(300, 380)
$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Multiline = $true; $txtLog.ReadOnly = $true
$txtLog.ScrollBars = 'Both'; $txtLog.WordWrap = $false
$txtLog.Location = New-Object System.Drawing.Point(330, 186)
$txtLog.Size = New-Object System.Drawing.Size(620, 380)
$txtLog.Font = New-Object System.Drawing.Font('Consolas', 9)
$script:txtLog = $txtLog
function New-Button([string]$Text, [int]$X, [int]$Width) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Text
    $button.Location = New-Object System.Drawing.Point($X, 580)
    $button.Size = New-Object System.Drawing.Size($Width, 34)
    $form.Controls.Add($button)
    return ,$button
}
$btnStart = New-Button '开始提交' 14 100
$btnStop = New-Button '停止' 124 70
$btnStop.Enabled = $false
$btnClear = New-Button '清空日志' 204 90
$btnOpenLog = New-Button '打开日志目录' 304 110
$btnOpenRec = New-Button '查看提交记录' 424 110
$lblStatus = New-Object System.Windows.Forms.Label
$lblStatus.Text = '就绪，请先登录'
$lblStatus.Location = New-Object System.Drawing.Point(550, 586)
$lblStatus.Size = New-Object System.Drawing.Size(400, 50)
$form.Controls.AddRange(@($lblToken, $txtToken, $btnLogin, $btnCheck, $panelFixed, $lblSerials, $txtSerials, $txtLog, $lblStatus))
Load-Config

$btnLogin.Add_Click({
    if ($script:Busy) { return }
    Set-Busy $true
    try { Show-OfficialLogin }
    catch { Write-Log $_.Exception.Message; $lblStatus.Text = '登录未完成' }
    finally { Set-Busy $false }
})
$btnCheck.Add_Click({
    if ($script:Busy) { return }
    Set-Busy $true
    try { [void](Test-Login $txtToken.Text.Trim()); $lblStatus.Text = '登录有效' }
    catch { Write-Log $_.Exception.Message; $lblStatus.Text = '请重新登录' }
    finally { Set-Busy $false }
})
$btnStart.Add_Click({
    if ($script:Busy) { return }
    Set-Busy $true
    $script:StopFlag = $false
    try {
        $serials = @(Get-Serials $txtSerials.Text)
        if ($serials.Count -eq 0) { throw '请先粘贴序列号' }
        $fixed = [pscustomobject]@{
            RepairClient = $txtRepairClient.Text.Trim(); Linkman = $txtLinkman.Text.Trim()
            Linknumber = $txtLinknumber.Text.Trim(); RebackFault = $txtFault.Text.Trim()
            RebackFaulttext = $txtFaultText.Text.Trim(); DealType = $txtDealType.Text.Trim()
            RepairMode = $txtRepairMode.Text.Trim()
        }
        Test-FixedSettings $fixed
        $delay = 0
        if (-not [int]::TryParse($txtDelay.Text.Trim(), [ref]$delay) -or $delay -lt 0 -or $delay -gt 600000) {
            throw '间隔毫秒必须是 0 至 600000 之间的整数'
        }
        $records = Read-Records
        Save-Config
        New-Item -ItemType Directory -Path $script:LogDir -Force | Out-Null
        $script:LogPath = Join-Path $script:LogDir ('submit_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.log')
        $token = $txtToken.Text.Trim()
        [void](Test-Login $token)
        Test-AccountSettings $script:LoginInfo $fixed
        $ok = 0; $failed = 0; $skipped = 0; $idx = 0; $r = $null
        Write-Log "新任务：$($serials.Count) 个去重后的序列号；间隔 $delay 毫秒。"
        foreach ($serial in $serials) {
            Invoke-UiPump
            if ($script:StopFlag) { break }
            $idx++
            $lblStatus.Text = "提交中 $idx / $($serials.Count)"
            if ($records[$serial] -match '待核对') {
                $skipped++; Write-Log "跳过待核对记录：$serial。请先在网页历史数据确认。"; continue
            }
            if ($chkSkip.Checked -and $records[$serial] -eq '成功') {
                $skipped++; Write-Log "跳过已成功记录：$serial"; continue
            }
            $r = Invoke-SubmitOne $serial $token $fixed
            Write-Log ("$serial ：" + $r.Message)
            if ($r.State -eq 'stopped') { break }
            if ($r.Success) { $ok++; $records[$serial] = '成功' }
            else {
                $failed++
                if (-not $r.Submitted) { Add-Record $serial $r.Model ('失败: ' + $r.Message) }
                if ($r.State -in @('auth', 'unknown')) {
                    if ($r.State -eq 'auth') { $txtToken.Clear() }
                    Write-Log '任务已停止，请处理上述问题后重新开始。'; break
                }
            }
            Wait-AsmpDelay $delay
        }
        $end = $(if ($script:StopFlag -or $idx -lt $serials.Count -or ($r -and $r.State -in @('auth','unknown'))) { '已停止' } else { '完成' })
        $lblStatus.Text = "$end ：成功 $ok，失败 $failed，跳过 $skipped"
        Write-Log $lblStatus.Text
    } catch {
        Write-Log ('任务已停止：' + $_.Exception.Message)
        $lblStatus.Text = '已停止，请查看日志；有待核对记录时勿直接重试'
    } finally { Set-Busy $false }
})
$btnStop.Add_Click({
    $script:StopFlag = $true
    Write-Log '收到停止指令：不会再开始新的提交；已发出的请求等待结果。'
    $btnStop.Enabled = $false
})
$btnClear.Add_Click({ $txtLog.Clear() })
$btnOpenLog.Add_Click({
    New-Item -ItemType Directory -Path $script:LogDir -Force | Out-Null
    Start-Process explorer.exe -ArgumentList ('"' + $script:LogDir + '"')
})
$btnOpenRec.Add_Click({
    if (Test-Path -LiteralPath $script:RecPath) { Start-Process notepad.exe -ArgumentList ('"' + $script:RecPath + '"') }
    else { Write-Log '还没有提交记录。' }
})
$form.Add_FormClosing({
    param($sender, $e)
    if ($script:Busy) {
        $e.Cancel = $true; $script:StopFlag = $true
        Write-Log '正在处理请求，请等待当前请求结束再关闭。'
        return
    }
    try { Save-Config } catch { Write-Log ('配置保存失败：' + $_.Exception.Message) }
})
if ($Login) { $form.Add_Shown({ $btnLogin.PerformClick() }) }
if ($SmokeTest) {
    $form.Add_Shown({
        try { Initialize-LoginLibrary; Save-Config; $script:SmokePassed = $true }
        catch { $script:SmokeError = $_.Exception.Message }
        finally { $form.Close() }
    })
}
try { [void]$form.ShowDialog() }
finally {
    $form.Dispose()
    $script:CurrentToken = ''
    $script:Mutex.ReleaseMutex(); $script:Mutex.Dispose()
}
if ($SmokeTest) {
    if (-not $script:SmokePassed) { throw $script:SmokeError }
    Write-Output 'UI_SMOKE_OK'
}
