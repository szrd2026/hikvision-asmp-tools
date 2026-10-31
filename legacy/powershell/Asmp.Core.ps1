# Pure request, payload and journal functions. Also used by tests without opening a UI.
Add-Type -AssemblyName System.Net.Http
$script:ApiBase = 'https://asmp.hikvision.com/api/sendRepairWeb'
$script:RecPath = Join-Path $PSScriptRoot 'submit_records.csv'
$script:StopFlag = $false
$script:PumpUi = $false

function Invoke-UiPump {
    if ($script:PumpUi) { [System.Windows.Forms.Application]::DoEvents() }
}

function Wait-AsmpDelay([int]$Milliseconds) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while ($clock.ElapsedMilliseconds -lt $Milliseconds -and -not $script:StopFlag) {
        Invoke-UiPump
        Start-Sleep -Milliseconds 20
    }
}

function Invoke-RmaPost {
    param([string]$Url, [string]$Token, [string]$Body)
    # Never redirect a credential-bearing request to another origin, or retry a POST.
    $uri = [uri]$Url
    if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'asmp.hikvision.com' -or $uri.Port -ne 443) {
        throw '请求地址必须为 ASMP 官方 HTTPS 地址'
    }
    $handler = New-Object Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $false
    $handler.CookieContainer.Add((New-Object Net.Cookie('asmp_sr_token', $Token, '/', 'asmp.hikvision.com')))
    $client = New-Object Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(90)
    $response = $null
    $result = [pscustomobject]@{ GotResp = $false; Status = 0; Text = '' }
    try {
        $client.DefaultRequestHeaders.Add('accessToken', $Token)
        $client.DefaultRequestHeaders.Referrer = [uri]'https://asmp.hikvision.com/sr/'
        $client.DefaultRequestHeaders.Add('Origin', 'https://asmp.hikvision.com')
        $content = New-Object Net.Http.StringContent($Body, [Text.Encoding]::UTF8, 'application/json')
        try {
            $task = $client.PostAsync($uri, $content)
            # Await without blocking WinForms. A sent submission must finish or time out;
            # cancelling it would not establish whether the server committed the RMA.
            while (-not $task.IsCompleted) { Invoke-UiPump; Start-Sleep -Milliseconds 20 }
            $response = $task.GetAwaiter().GetResult()
            $read = $response.Content.ReadAsStringAsync()
            while (-not $read.IsCompleted) { Invoke-UiPump; Start-Sleep -Milliseconds 20 }
            $result.Text = $read.GetAwaiter().GetResult()
            $result.Status = [int]$response.StatusCode
            $result.GotResp = $true
        } finally { $content.Dispose() }
    } catch {
        # Do not put a potentially sensitive HTTP exception/response into the log.
        $result.Text = '网络连接失败或请求超时'
    } finally {
        if ($response) { $response.Dispose() }
        $client.Dispose()
    }
    return $result
}

function Get-AsmpResponse($Response) {
    $obj = $null
    try { $obj = $Response.Text | ConvertFrom-Json -ErrorAction Stop } catch {}
    $code = ''; $message = ''
    if ($obj) { $code = [string]$obj.code; $message = [string]$obj.msg }
    $auth = $Response.Status -in @(401, 403) -or $code -in @('003', '013') -or $message -match 'notLogin|未登录|登录失效|登录过期|重新登录'
    $httpOk = $Response.GotResp -and $Response.Status -ge 200 -and $Response.Status -lt 300
    [pscustomobject]@{
        Object = $obj; Code = $code; AuthExpired = $auth
        Success = ($httpOk -and $code -ceq '000')
        Definitive = ($httpOk -and $null -ne $obj -and $code -ne '')
        Message = $(if ($message) { $message } elseif (-not $Response.GotResp) { '网络连接失败或超时' } else { 'HTTP ' + $Response.Status + ' 或响应格式异常' })
    }
}

function Get-Serials([string]$Text) {
    $seen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($s in ($Text -split '[\r\n\t,，;；]+')) {
        $s = $s.Trim()
        if (-not $s) { continue }
        if ($s -match '[\x00-\x20\x7f"\\]') { throw "序列号含空白或非法字符，请确认只粘贴序列号列：$s" }
        if ($s.Length -gt 128) { throw '序列号超过 128 个字符，请检查粘贴内容' }
        if ($seen.Add($s)) { $s }
    }
}

function Test-FixedSettings($Fixed) {
    foreach ($key in @('RepairClient', 'Linkman', 'Linknumber', 'RebackFault', 'RebackFaulttext')) {
        if ([string]::IsNullOrWhiteSpace([string]$Fixed.$key)) { throw "必填设置不能为空：$key" }
    }
    if ([string]$Fixed.DealType -notin @('0', '1', '2')) { throw '处理方式只能是 0（维修）、1（一年包换）、2（本地服务）' }
    if ([string]$Fixed.RepairMode -notin @('0', '1', '2')) { throw '接修方式只能是 0（送修）、1（上门取件）、2（寄修）' }
}

function New-RmaPayload([string]$Serial, $Data, $Fixed) {
    Test-FixedSettings $Fixed
    if ([string]::IsNullOrWhiteSpace([string]$Data.productModel)) { throw '查询未返回产品型号，停止此条提交' }
    if ([string]$Fixed.DealType -eq '1' -and [string]$Data.changeType -notin @('0', '1')) {
        throw '一年包换需要更换方式，查询结果未提供；请在网页完成这类登记'
    }
    $detail = [ordered]@{
        uuid = [guid]::NewGuid().ToString(); isSend = 1; serialId = $Serial
        rebackFault = [string]$Fixed.RebackFault; rebackFaulttext = [string]$Fixed.RebackFaulttext
        dealType = [string]$Fixed.DealType
        changeType = $(if ([string]$Fixed.DealType -eq '1') { [string]$Data.changeType } else { '' })
        stateStr = 'new'; isEdit = $true; addType = 'hand'; isSerial = $true
        isExchangeAmountMaterial = $(if ($null -eq $Data.isExchangeAmountMaterial) { 0 } else { $Data.isExchangeAmountMaterial })
    }
    # Preserve server-derived product/QA/accessory fields as the official form does.
    foreach ($key in @('productModel', 'repairEndtime', 'repairSituation', 'clientName', 'randomAttach',
        'saleTime', 'hxwl', 'xltyp', 'qaCheckResult', 'qaCheckContent', 'qaCheckUser', 'qaCheckTime',
        'materialCategoryCode', 'materialGroup', 'materialNumber', 'materialDesc',
        'salesOrderNum', 'salesOrderLineNum', 'customerId')) {
        $detail[$key] = [string]$Data.$key
    }
    if ($null -ne $Data.zprPrice) { $detail['zprPrice'] = $Data.zprPrice }
    # Fixed web fields are intentionally not exposed as additional settings.
    [ordered]@{
        createTime = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        city = ''; area = ''; province = $null; address = $null; fax = $null; remark = $null
        repairClient = [string]$Fixed.RepairClient; linkman = [string]$Fixed.Linkman
        linknumber = [string]$Fixed.Linknumber; repairMode = [int]$Fixed.RepairMode
        isSend = 1; state = 1; isMessage = '0'; rmaDetailList = @($detail)
    }
}

function Read-Records {
    $map = @{}
    $succeeded = @{}
    if (Test-Path -LiteralPath $script:RecPath) {
        # Fail closed: a broken/unreadable journal must not silently enable duplicates.
        $header = Get-Content -LiteralPath $script:RecPath -Encoding UTF8 -TotalCount 1 -ErrorAction Stop
        if (-not $header) { throw '提交记录为空或损坏，请先核对网页历史数据' }
        $probe = @((($header + "`r`n,,,") | ConvertFrom-Csv -ErrorAction Stop))
        if (($probe[0].PSObject.Properties.Name -join ',') -cne '时间,序列号,型号,结果') { throw '提交记录表头异常，请先核对记录文件' }
        $rows = @(Import-Csv -LiteralPath $script:RecPath -Encoding UTF8 -ErrorAction Stop)
        foreach ($row in $rows) {
            $serial = [string]$row.序列号
            if (-not $serial) { throw '提交记录格式异常，缺少序列号；请先检查记录文件' }
            if ([string]::IsNullOrEmpty([string]$row.结果)) { throw '提交记录格式异常，缺少结果' }
            $result = [string]$row.结果
            if ($result -eq '成功') { $succeeded[$serial] = $true; $map[$serial] = '成功' }
            elseif ($result -match '待核对') { $map[$serial] = $result }
            elseif ($result -match '^失败[:：]') {
                $map[$serial] = $(if ($succeeded[$serial]) { '成功' } else { $result })
            } else { throw '提交记录存在未知结果，停止以避免重复提交' }
        }
    }
    return $map
}

function Add-Record([string]$Serial, [string]$Model, [string]$Result) {
    $row = [pscustomobject][ordered]@{ 时间 = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'; 序列号 = $Serial; 型号 = $Model; 结果 = $Result }
    $lines = @($row | ConvertTo-Csv -NoTypeInformation)
    $stream = New-Object IO.FileStream($script:RecPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $new = $stream.Length -eq 0
        [void]$stream.Seek(0, [IO.SeekOrigin]::End)
        if ($new) {
            $bom = (New-Object Text.UTF8Encoding($true)).GetPreamble()
            $stream.Write($bom, 0, $bom.Length)
        }
        $text = $(if ($new) { ($lines -join "`r`n") } else { $lines[-1] }) + "`r`n"
        $bytes = [Text.Encoding]::UTF8.GetBytes($text)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally { $stream.Dispose() }
}

function Invoke-SubmitOne([string]$Serial, [string]$Token, $Fixed) {
    $r = [pscustomobject]@{ Success = $false; Model = ''; Message = ''; State = 'failed'; Submitted = $false }
    Write-Log "查询序列号：$Serial"
    $body = @{ serialId = $Serial } | ConvertTo-Json -Compress
    $query = Get-AsmpResponse (Invoke-RmaPost "$script:ApiBase/rmaManage/getRmaDetailBySerial" $Token $body)
    if ($query.AuthExpired) { $r.State = 'auth'; $r.Message = '登录已失效，请重新登录'; return $r }
    if (-not $query.Success -or -not $query.Object.data) { $r.Message = '查询失败：' + $query.Message; return $r }
    $r.Model = [string]$query.Object.data.productModel
    try { $payload = New-RmaPayload $Serial $query.Object.data $Fixed | ConvertTo-Json -Depth 8 -Compress }
    catch { $r.Message = $_.Exception.Message; return $r }
    # Re-check after the UI processed Stop while awaiting the query.
    if ($script:StopFlag) { $r.State = 'stopped'; $r.Message = '已停止，未提交此条'; return $r }
    # Durable intent BEFORE the non-idempotent POST, so a crash cannot enable replay.
    Add-Record $Serial $r.Model '提交中（待核对）'
    $r.Submitted = $true
    Write-Log "提交登记：$Serial（$($r.Model)）"
    try { $sub = Get-AsmpResponse (Invoke-RmaPost "$script:ApiBase/rmaManage/setNewRma" $Token $payload) }
    catch { $sub = $null }
    if ($sub -and $sub.Success) {
        $r.Success = $true; $r.State = 'success'; $r.Message = '成功'
        Add-Record $Serial $r.Model '成功'
    } elseif ($sub -and $sub.AuthExpired) {
        $r.State = 'auth'; $r.Message = '登录已失效，请重新登录'
        Add-Record $Serial $r.Model ('失败: ' + $r.Message)
    } elseif ($sub -and $sub.Definitive) {
        $r.Message = '服务端拒绝：' + $sub.Message
        Add-Record $Serial $r.Model ('失败: ' + $r.Message)
    } else {
        $r.State = 'unknown'; $r.Message = '提交结果待核对，请先在网页历史数据检查，禁止直接重试'
        Add-Record $Serial $r.Model ('待核对: ' + $r.Message)
    }
    return $r
}
