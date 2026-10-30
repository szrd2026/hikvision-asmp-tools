# ============================================================================
# 海康威视 ASMP 自动提交工具（独立版，免安装）
# 功能: 粘贴序列号 -> 逐条查询明细 -> 组装 setNewRma 报文 -> 自动提交登记
# 日志: 界面右侧实时显示；每次运行自动保存到 logs\submit_时间戳.log
#       （含每次请求/响应的完整内容，方便排查问题）
# 使用: 双击 Start-Submit.bat
# ============================================================================
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:ApiGet = 'https://asmp.hikvision.com/api/sendRepairWeb/rmaManage/getRmaDetailBySerial'
$script:ApiSub = 'https://asmp.hikvision.com/api/sendRepairWeb/rmaManage/setNewRma'
$script:Root = $PSScriptRoot
$script:CfgPath = Join-Path $script:Root 'submit_config.json'
$script:RecPath = Join-Path $script:Root 'submit_records.csv'
$script:LogDir = Join-Path $script:Root 'logs'
$script:LogPath = $null
$script:StopFlag = $false

# ============================ 日志 ============================
function Write-Log {
    param([string]$Msg)
    $line = '[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss'), $Msg
    if ($script:txtLog) {
        $script:txtLog.AppendText($line + "`r`n")
        $script:txtLog.SelectionStart = $script:txtLog.TextLength
        $script:txtLog.ScrollToCaret()
    }
    if ($script:LogPath) {
        try { [IO.File]::AppendAllText($script:LogPath, $line + "`r`n", [Text.Encoding]::UTF8) } catch {}
    }
}

# ============================ HTTP ============================
function Invoke-RmaPost {
    param([string]$Url, [string]$Token, [string]$Body)
    $res = [pscustomobject]@{ GotResp = $false; Status = 0; Text = '' }
    try {
        $req = [Net.HttpWebRequest]::Create($Url)
        $req.Method = 'POST'
        $req.ContentType = 'application/json;charset=UTF-8'
        $req.Accept = 'application/json, text/plain, */*'
        $req.Timeout = 20000
        $req.UserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        $req.Headers.Add('accesstoken', $Token)
        $cc = New-Object System.Net.CookieContainer
        $ck = New-Object System.Net.Cookie('asmp_sr_token', $Token, '/', 'asmp.hikvision.com')
        $cc.Add($ck)
        $req.CookieContainer = $cc
        $bytes = [Text.Encoding]::UTF8.GetBytes($Body)
        $req.ContentLength = $bytes.Length
        $s = $req.GetRequestStream(); $s.Write($bytes, 0, $bytes.Length); $s.Close()
        $resp = $req.GetResponse()
        $res.Status = [int]$resp.StatusCode
        $reader = New-Object IO.StreamReader($resp.GetResponseStream(), [Text.Encoding]::UTF8)
        $res.Text = $reader.ReadToEnd(); $reader.Close(); $resp.Close()
        $res.GotResp = $true
    } catch [Net.WebException] {
        $er = $_.Exception
        $r = $er.Response
        if ($r) {
            $res.Status = [int]$r.StatusCode
            try {
                $reader = New-Object IO.StreamReader($r.GetResponseStream(), [Text.Encoding]::UTF8)
                $res.Text = $reader.ReadToEnd(); $reader.Close()
            } catch {}
            $res.GotResp = $true
        }
        if ($res.Text -eq '') { $res.Text = $er.Message }
    } catch {
        $res.GotResp = $false
        $res.Status = 0
        $res.Text = $_.Exception.Message
    }
    return $res
}

# ============================ 提交一条 ============================
function Invoke-SubmitOne {
    param([string]$Serial, [string]$Token, $Fixed)
    $r = [pscustomobject]@{ Success = $false; Model = ''; Message = '' }
    Write-Log '----------------------------------------'
    Write-Log "序列号: $Serial"

    # 1) 查询明细
    $body = '{"serialId":"' + $Serial + '"}'
    Write-Log "步骤1 查询明细 请求: $body"
    $res = Invoke-RmaPost -Url $script:ApiGet -Token $Token -Body $body
    if (-not $res.GotResp) {
        Write-Log "步骤1 查询明细 网络错误: $($res.Text)"
        $r.Message = '查询明细网络错误: ' + $res.Text
        return $r
    }
    Write-Log "步骤1 查询明细 响应 HTTP $($res.Status): $($res.Text)"
    $obj = $null
    try { $obj = $res.Text | ConvertFrom-Json } catch { $obj = $null }
    if (-not $obj -or [string]$obj.code -ne '000' -or -not $obj.data) {
        $code = ''
        if ($obj) { $code = [string]$obj.code }
        $msg = ''
        if ($obj -and $obj.msg) { $msg = [string]$obj.msg }
        Write-Log "步骤1 查询明细 失败: code=$code msg=$msg"
        if ($code -eq '013' -or $msg -like '*notLogin*' -or $msg -like '*登录*') {
            $r.Message = 'notLogin：accesstoken 已过期或失效，请重新从浏览器复制（F12 → 网络 → 任意 asmp 请求 → 请求标头 accesstoken）'
        } else {
            $r.Message = '查询明细失败: ' + $msg
        }
        return $r
    }
    $d = $obj.data
    $r.Model = [string]$d.productModel
    Write-Log "步骤1 查询明细 成功，型号: $($r.Model)"

    # 2) 组装报文
    $detail = [ordered]@{}
    $detail['uuid'] = [guid]::NewGuid().ToString()
    $detail['isSend'] = 1
    $detail['serialId'] = $Serial
    $detail['productModel'] = [string]$d.productModel
    $detail['repairEndtime'] = [string]$d.repairEndtime
    $detail['repairSituation'] = [string]$d.repairSituation
    $detail['clientName'] = [string]$d.clientName
    $detail['rebackFault'] = [string]$Fixed.RebackFault
    $detail['rebackFaulttext'] = [string]$Fixed.RebackFaulttext
    $detail['randomAttach'] = $null
    $detail['dealType'] = [string]$Fixed.DealType
    $detail['changeType'] = $null
    $detail['stateStr'] = 'new'
    $detail['isEdit'] = $true
    $detail['xltyp'] = ''
    $detail['saleTime'] = [string]$d.saleTime
    $detail['hxwl'] = [string]$d.hxwl
    $detail['qaCheckResult'] = ''
    $detail['qaCheckContent'] = ''
    $detail['qaCheckUser'] = ''
    $detail['qaCheckTime'] = ''
    $detail['addType'] = 'hand'
    $detail['materialCategoryCode'] = [string]$d.materialCategoryCode
    $detail['materialGroup'] = [string]$d.materialGroup
    $detail['materialNumber'] = [string]$d.materialNumber
    $detail['isSerial'] = $true
    if ($null -eq $d.zprPrice) { $detail['zprPrice'] = 0 } else { $detail['zprPrice'] = $d.zprPrice }
    $detail['materialDesc'] = [string]$d.materialDesc
    $detail['salesOrderNum'] = [string]$d.salesOrderNum
    $detail['salesOrderLineNum'] = [string]$d.salesOrderLineNum
    $detail['customerId'] = [string]$d.customerId
    if ($null -eq $d.isExchangeAmountMaterial) { $detail['isExchangeAmountMaterial'] = 1 } else { $detail['isExchangeAmountMaterial'] = $d.isExchangeAmountMaterial }

    $top = [ordered]@{}
    $top['createTime'] = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $top['city'] = ''
    $top['area'] = ''
    $top['repairClient'] = [string]$Fixed.RepairClient
    $top['province'] = $null
    $top['address'] = $null
    $top['linkman'] = [string]$Fixed.Linkman
    $top['linknumber'] = [string]$Fixed.Linknumber
    $top['fax'] = $null
    $top['remark'] = $null
    $mode = 2
    if ([string]$Fixed.RepairMode -match '^\d+$') { $mode = [int]$Fixed.RepairMode }
    $top['repairMode'] = $mode
    $top['isSend'] = 1
    $top['state'] = 1
    $top['isMessage'] = '0'
    $top['rmaDetailList'] = @($detail)
    $payload = $top | ConvertTo-Json -Depth 8
    Write-Log "步骤2 提交报文: $payload"

    # 3) 提交
    $res = Invoke-RmaPost -Url $script:ApiSub -Token $Token -Body $payload
    if (-not $res.GotResp) {
        Write-Log "步骤3 提交 网络错误: $($res.Text)"
        $r.Message = '提交网络错误: ' + $res.Text
        return $r
    }
    Write-Log "步骤3 提交 响应 HTTP $($res.Status): $($res.Text)"
    $sub = $null
    try { $sub = $res.Text | ConvertFrom-Json } catch { $sub = $null }
    if ($sub -and [string]$sub.code -eq '000') {
        $r.Success = $true
        $r.Message = '成功'
        Write-Log '结果: 成功'
    } else {
        $msg = ''
        if ($sub -and $sub.msg) { $msg = [string]$sub.msg }
        if ($msg -eq '') { $msg = $res.Text }
        if (($sub -and [string]$sub.code -eq '013') -or $msg -like '*notLogin*' -or $msg -like '*登录*') {
            $msg = 'notLogin：accesstoken 已过期或失效，请重新从浏览器复制 accesstoken'
        }
        $r.Message = $msg
        Write-Log "结果: 失败 ($msg)"
    }
    return $r
}

# ============================ 提交记录（防重复提交）============================
function Read-Records {
    $map = @{}
    if (Test-Path $script:RecPath) {
        try {
            $rows = Import-Csv $script:RecPath -Encoding UTF8
            foreach ($row in $rows) {
                $s = [string]$row.序列号
                if ($s -ne '') { $map[$s] = [string]$row.结果 }
            }
        } catch {}
    }
    return $map
}

function Add-Record {
    param([string]$Serial, [string]$Model, [string]$Result)
    try {
        if (-not (Test-Path $script:RecPath)) {
            [IO.File]::WriteAllText($script:RecPath, "时间,序列号,型号,结果`r`n", (New-Object Text.UTF8Encoding($true)))
        }
        $t = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $line = '"{0}","{1}","{2}","{3}"' -f $t, ($Serial -replace '"', '""'), ($Model -replace '"', '""'), ($Result -replace '"', '""')
        [IO.File]::AppendAllText($script:RecPath, $line + "`r`n", [Text.Encoding]::UTF8)
    } catch {
        Write-Log "提交记录写入失败: $($_.Exception.Message)"
    }
}

# ============================ 配置读写 ============================
function Save-Config {
    try {
        $cfg = [ordered]@{
            token = $txtToken.Text.Trim()
            repairClient = $txtRepairClient.Text.Trim()
            linkman = $txtLinkman.Text.Trim()
            linknumber = $txtLinknumber.Text.Trim()
            rebackFault = $txtFault.Text.Trim()
            rebackFaulttext = $txtFaultText.Text.Trim()
            dealType = $txtDealType.Text.Trim()
            repairMode = $txtRepairMode.Text.Trim()
            delay = $txtDelay.Text.Trim()
            skip = ([bool]$chkSkip.Checked)
        }
        $cfg | ConvertTo-Json | Set-Content -Path $script:CfgPath -Encoding UTF8
    } catch {}
}

function Load-Config {
    $cfg = $null
    if (Test-Path $script:CfgPath) {
        try { $cfg = Get-Content -Raw -Encoding UTF8 $script:CfgPath | ConvertFrom-Json } catch { $cfg = $null }
    }
    if ($cfg) {
        try { $txtToken.Text = [string]$cfg.token } catch {}
        try { $txtRepairClient.Text = [string]$cfg.repairClient } catch {}
        try { $txtLinkman.Text = [string]$cfg.linkman } catch {}
        try { $txtLinknumber.Text = [string]$cfg.linknumber } catch {}
        try { $txtFault.Text = [string]$cfg.rebackFault } catch {}
        try { $txtFaultText.Text = [string]$cfg.rebackFaulttext } catch {}
        try { $txtDealType.Text = [string]$cfg.dealType } catch {}
        try { $txtRepairMode.Text = [string]$cfg.repairMode } catch {}
        try { $txtDelay.Text = [string]$cfg.delay } catch {}
        try { $chkSkip.Checked = [bool]$cfg.skip } catch {}
    }
}

# ============================ GUI ============================
$form = New-Object System.Windows.Forms.Form
$form.Text = '海康威视 ASMP 自动提交工具'
$form.Size = New-Object System.Drawing.Size(980, 680)
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object System.Drawing.Font('Microsoft YaHei', 9)

$lblToken = New-Object System.Windows.Forms.Label
$lblToken.Text = 'accesstoken（F12 -> 网络 -> 任意 asmp 请求 -> 请求标头 复制）:'
$lblToken.Location = New-Object System.Drawing.Point(14, 14)
$lblToken.AutoSize = $true

$txtToken = New-Object System.Windows.Forms.TextBox
$txtToken.Location = New-Object System.Drawing.Point(14, 38)
$txtToken.Size = New-Object System.Drawing.Size(936, 23)

# ---- 固定信息（FlowLayout，自动换行）----
$panelFixed = New-Object System.Windows.Forms.FlowLayoutPanel
$panelFixed.Location = New-Object System.Drawing.Point(14, 68)
$panelFixed.Size = New-Object System.Drawing.Size(936, 66)
$panelFixed.FlowDirection = 'LeftToRight'
$panelFixed.WrapContents = $true

function New-Field([string]$Label, [int]$Width, [string]$Default) {
    $p = New-Object System.Windows.Forms.Panel
    $p.Size = New-Object System.Drawing.Size(($Width + 70), 24)
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $Label
    $l.AutoSize = $true
    $l.Location = New-Object System.Drawing.Point(0, 4)
    $t = New-Object System.Windows.Forms.TextBox
    $t.Text = $Default
    $t.Location = New-Object System.Drawing.Point(($l.PreferredWidth + 4), 1)
    $t.Size = New-Object System.Drawing.Size($Width, 21)
    $p.Controls.Add($l) | Out-Null
    $p.Controls.Add($t) | Out-Null
    return ,$t
}
$txtRepairClient = New-Field '维修客户:' 90 '示例维修网点'
$txtLinkman      = New-Field '联系人:' 60 '张三'
$txtLinknumber   = New-Field '电话:' 95 '13800138000'
$txtFault        = New-Field '故障类型:' 60 '其他'
$txtFaultText    = New-Field '故障描述:' 250 '设备异常，客户要求换新'
$txtDealType     = New-Field '处理方式:' 40 '2'
$txtRepairMode   = New-Field '维修方式:' 40 '2'
$txtDelay        = New-Field '间隔毫秒:' 50 '500'

foreach ($tb in @($txtRepairClient, $txtLinkman, $txtLinknumber, $txtFault, $txtFaultText, $txtDealType, $txtRepairMode, $txtDelay)) {
    $panelFixed.Controls.Add($tb.Parent) | Out-Null
}

$chkSkip = New-Object System.Windows.Forms.CheckBox
$chkSkip.Text = '跳过已成功提交的序列号'
$chkSkip.Checked = $true
$chkSkip.AutoSize = $true
$panelFixed.Controls.Add($chkSkip) | Out-Null

$lblSerials = New-Object System.Windows.Forms.Label
$lblSerials.Text = '序列号（从 Excel 复制，每行一个，可一次粘贴多条）:'
$lblSerials.Location = New-Object System.Drawing.Point(14, 142)
$lblSerials.AutoSize = $true

$txtSerials = New-Object System.Windows.Forms.TextBox
$txtSerials.Multiline = $true
$txtSerials.ScrollBars = 'Vertical'
$txtSerials.Location = New-Object System.Drawing.Point(14, 166)
$txtSerials.Size = New-Object System.Drawing.Size(300, 400)

$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Multiline = $true
$txtLog.ReadOnly = $true
$txtLog.ScrollBars = 'Both'
$txtLog.WordWrap = $false
$txtLog.Location = New-Object System.Drawing.Point(330, 166)
$txtLog.Size = New-Object System.Drawing.Size(620, 400)
$txtLog.Font = New-Object System.Drawing.Font('Consolas', 9)

$script:txtLog = $txtLog

$btnStart = New-Object System.Windows.Forms.Button
$btnStart.Text = '开始提交'
$btnStart.Location = New-Object System.Drawing.Point(14, 580)
$btnStart.Size = New-Object System.Drawing.Size(100, 34)

$btnStop = New-Object System.Windows.Forms.Button
$btnStop.Text = '停止'
$btnStop.Location = New-Object System.Drawing.Point(124, 580)
$btnStop.Size = New-Object System.Drawing.Size(70, 34)

$btnClear = New-Object System.Windows.Forms.Button
$btnClear.Text = '清空日志'
$btnClear.Location = New-Object System.Drawing.Point(204, 580)
$btnClear.Size = New-Object System.Drawing.Size(90, 34)

$btnOpenLog = New-Object System.Windows.Forms.Button
$btnOpenLog.Text = '打开日志目录'
$btnOpenLog.Location = New-Object System.Drawing.Point(304, 580)
$btnOpenLog.Size = New-Object System.Drawing.Size(110, 34)

$btnOpenRec = New-Object System.Windows.Forms.Button
$btnOpenRec.Text = '查看提交记录'
$btnOpenRec.Location = New-Object System.Drawing.Point(424, 580)
$btnOpenRec.Size = New-Object System.Drawing.Size(110, 34)

$lblStatus = New-Object System.Windows.Forms.Label
$lblStatus.Text = '就绪'
$lblStatus.Location = New-Object System.Drawing.Point(560, 590)
$lblStatus.Size = New-Object System.Drawing.Size(390, 24)

$form.Controls.AddRange(@($lblToken, $txtToken, $panelFixed, $lblSerials, $txtSerials, $txtLog, $btnStart, $btnStop, $btnClear, $btnOpenLog, $btnOpenRec, $lblStatus))

Load-Config

$btnStart.Add_Click({
    $serials = @($txtSerials.Text -split "[\r\n,，;；]+" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
    if ($serials.Count -eq 0) { Write-Log '请先粘贴序列号'; return }
    $token = $txtToken.Text.Trim()
    if ($token -eq '') { Write-Log '请先填写 accesstoken'; return }

    New-Item -ItemType Directory -Force -Path $script:LogDir | Out-Null
    $script:LogPath = Join-Path $script:LogDir ('submit_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
    [IO.File]::WriteAllText($script:LogPath, '', [Text.Encoding]::UTF8)

    $Fixed = [pscustomobject]@{
        RepairClient = $txtRepairClient.Text.Trim()
        Linkman = $txtLinkman.Text.Trim()
        Linknumber = $txtLinknumber.Text.Trim()
        RebackFault = $txtFault.Text.Trim()
        RebackFaulttext = $txtFaultText.Text.Trim()
        DealType = $txtDealType.Text.Trim()
        RepairMode = $txtRepairMode.Text.Trim()
    }
    $masked = $token
    if ($token.Length -ge 8) { $masked = $token.Substring(0, 4) + '****' + $token.Substring($token.Length - 4) }
    $delay = 500
    if ($txtDelay.Text.Trim() -match '^\d+$') { $delay = [int]$txtDelay.Text.Trim() }
    $skipDone = $chkSkip.Checked

    Write-Log '==================== 新的提交任务 ===================='
    Write-Log ('日志文件: ' + $script:LogPath)
    Write-Log ('accesstoken: ' + $masked + '（日志中已打码）')
    Write-Log ('固定信息: repairClient=' + $Fixed.RepairClient + ' | linkman=' + $Fixed.Linkman + ' | linknumber=' + $Fixed.Linknumber + ' | rebackFault=' + $Fixed.RebackFault + ' | rebackFaulttext=' + $Fixed.RebackFaulttext + ' | dealType=' + $Fixed.DealType + ' | repairMode=' + $Fixed.RepairMode)
    Write-Log ('本次序列号数量: ' + $serials.Count + ' | 间隔: ' + $delay + 'ms | 跳过已提交: ' + $skipDone)

    $records = Read-Records
    $script:StopFlag = $false
    $btnStart.Enabled = $false
    $okCnt = 0; $failCnt = 0; $skipCnt = 0; $idx = 0
    foreach ($s in $serials) {
        if ($script:StopFlag) { Write-Log '用户手动停止'; break }
        $idx++
        $lblStatus.Text = "提交中 $idx / $($serials.Count)"
        [System.Windows.Forms.Application]::DoEvents()
        if ($skipDone -and $records.ContainsKey($s) -and ($records[$s] -like '*成功*')) {
            $skipCnt++
            Write-Log "跳过（此前已成功提交）: $s"
            continue
        }
        $r = Invoke-SubmitOne -Serial $s -Token $token -Fixed $Fixed
        if ($r.Success) {
            $okCnt++
            Add-Record $s $r.Model '成功'
            $records[$s] = '成功'
        } else {
            $failCnt++
            Add-Record $s $r.Model ('失败: ' + $r.Message)
            $records[$s] = '失败: ' + $r.Message
        }
        if ($delay -gt 0) { Start-Sleep -Milliseconds $delay }
    }
    $btnStart.Enabled = $true
    Write-Log ('==================== 任务结束：成功 ' + $okCnt + ' 条，失败 ' + $failCnt + ' 条，跳过 ' + $skipCnt + ' 条 ====================')
    $lblStatus.Text = "完成：成功 $okCnt，失败 $failCnt，跳过 $skipCnt"
    Save-Config
})

$btnStop.Add_Click({
    $script:StopFlag = $true
    Write-Log '收到停止指令，当前条提交完后停止...'
})

$btnClear.Add_Click({
    $txtLog.Clear()
})

$btnOpenLog.Add_Click({
    if (-not (Test-Path $script:LogDir)) { New-Item -ItemType Directory -Force -Path $script:LogDir | Out-Null }
    Start-Process explorer.exe $script:LogDir
})

$btnOpenRec.Add_Click({
    if (Test-Path $script:RecPath) {
        Start-Process notepad.exe $script:RecPath
    } else {
        Write-Log '还没有提交记录文件（提交过之后才会生成 submit_records.csv）'
    }
})

$form.Add_FormClosing({
    Save-Config
})

$form.ShowDialog() | Out-Null
