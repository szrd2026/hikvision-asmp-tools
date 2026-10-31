$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path $PSScriptRoot) 'Asmp.Core.ps1')
function Write-Log([string]$Message) {}
$script:Count = 0
function Assert($Condition, [string]$Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    $script:Count++
}
function Assert-Throws([scriptblock]$Action, [string]$Message) {
    $thrown = $false
    try { & $Action } catch { $thrown = $true }
    Assert $thrown $Message
}
$root = Join-Path (Split-Path $PSScriptRoot) ('.tmp\tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root -Force | Out-Null
$script:RecPath = Join-Path $root 'journal.csv'
$fixed = [pscustomobject]@{
    RepairClient = '测试客户'; Linkman = '测试'; Linknumber = '010-12345678'
    RebackFault = '其他'; RebackFaulttext = '测试故障'; DealType = '2'; RepairMode = '2'
}
$data = [pscustomobject]@{
    productModel = 'DS-TEST'; qaCheckResult = 'Q'; qaCheckContent = 'server content'
    randomAttach = '电源'; xltyp = 'server type'; zprPrice = 12.5
}
$payload = New-RmaPayload 'ABC001' $data $fixed
$detail = $payload.rmaDetailList[0]
Assert ($detail.isExchangeAmountMaterial -eq 0) 'missing exchange flag defaults to zero'
Assert ($detail.qaCheckResult -eq 'Q' -and $detail.randomAttach -eq '电源' -and $detail.xltyp -eq 'server type') 'server product fields preserved'
Assert ($detail.zprPrice -eq 12.5) 'price preserved as number'
Assert ($payload.isSend -eq 1 -and $payload.isMessage -ceq '0' -and $payload.state -eq 1) 'fixed form fields preserved'
Assert ((@((($payload | ConvertTo-Json -Depth 8) | ConvertFrom-Json).rmaDetailList)).Count -eq 1) 'detail remains array'
Assert (@(Get-Serials "ABC001`r`nabc001`tXYZ002，XYZ002;Z003").Count -eq 3) 'input deduplicated including Excel tabs'
Assert-Throws { Get-Serials 'ABC"001' } 'quotes rejected'
Assert-Throws { Get-Serials 'ABC 001' } 'embedded whitespace rejected'
$fixed.DealType = '9'; Assert-Throws { Test-FixedSettings $fixed } 'invalid deal type rejected'; $fixed.DealType = '2'
$fixed.RepairMode = '2147483648'; Assert-Throws { Test-FixedSettings $fixed } 'overflowing mode rejected'; $fixed.RepairMode = '2'
$fixed.Linkman = ''; Assert-Throws { Test-FixedSettings $fixed } 'empty required field rejected'; $fixed.Linkman = '测试'
$fixed.DealType = '1'; Assert-Throws { New-RmaPayload 'A' $data $fixed } 'exchange without change type rejected'; $fixed.DealType = '2'
Assert-Throws { New-RmaPayload 'A' ([pscustomobject]@{}) $fixed } 'missing product model rejected'
$account = [pscustomobject]@{ currentUser = [pscustomobject]@{ permissionList = @([pscustomobject]@{ code = 'SR02'; value = 0 }) }; currentCollectingPoint = [pscustomobject]@{ localRepair = 1; hikExchange = 0 } }
Test-AccountSettings $account $fixed
$fixed.DealType = '0'; Assert-Throws { Test-AccountSettings $account $fixed } 'fixed local-service mode enforced'; $fixed.DealType = '2'
$account.currentCollectingPoint.localRepair = 0
Assert-Throws { Test-AccountSettings $account $fixed } 'local service requires account capability'
$account.currentUser.permissionList[0].value = 1
Assert-Throws { Test-AccountSettings $account $fixed } 'registration permission enforced'

function Reply([int]$Status, [string]$Text) { [pscustomobject]@{ GotResp = ($Status -ne 0); Status = $Status; Text = $Text } }
Assert (Get-AsmpResponse (Reply 200 '{"code":"003","data":{"r":"https://example.invalid"}}')).AuthExpired '003 login redirect detected'
Assert (Get-AsmpResponse (Reply 200 '{"code":"013"}')).AuthExpired '013 login expiry detected'
Assert (Get-AsmpResponse (Reply 401 'unauthorized')).AuthExpired 'HTTP401 detected'
Assert (-not (Get-AsmpResponse (Reply 500 '{"code":"000"}')).Success) 'HTTP500 cannot be success'
Assert (-not (Get-AsmpResponse (Reply 200 '<html>login</html>')).Definitive) 'HTML not a definitive business reply'

Add-Record 'A' 'Model,with"quote' '成功'
Add-Record 'A' 'Model' '失败: 后一次被拒绝'
Assert ((Read-Records)['A'] -eq '成功') 'later rejection does not erase historical success'
Assert ((Import-Csv -LiteralPath $script:RecPath -Encoding UTF8)[0].型号 -eq 'Model,with"quote') 'CSV escaped round trip'
Add-Record 'A' 'Model' '提交中（待核对）'
Assert ((Read-Records)['A'] -match '待核对') 'new in-flight attempt takes priority over old success'
Add-Record 'A' 'Model' '失败: 明确拒绝'
Assert ((Read-Records)['A'] -eq '成功') 'definitive rejection restores old success protection'

$script:Requests = New-Object Collections.ArrayList
$script:Replies = New-Object Collections.Queue
$script:StopOnQuery = $false
$script:RealPost = (Get-Item function:Invoke-RmaPost).ScriptBlock
function Invoke-RmaPost([string]$Url, [string]$Token, [string]$Body) {
    [void]$script:Requests.Add($Url)
    if ($Url.EndsWith('/setNewRma')) { Assert ((Read-Records)['TEST'] -match '待核对') 'durable intent exists before POST' }
    if ($script:StopOnQuery -and $Url.EndsWith('/getRmaDetailBySerial')) { $script:StopFlag = $true }
    if ($script:Replies.Count -eq 0) { throw 'Unexpected HTTP request in offline tests' }
    return $script:Replies.Dequeue()
}
function New-Case([string]$Name) {
    $script:RecPath = Join-Path $root ($Name + '.csv')
    $script:StopFlag = $false; $script:StopOnQuery = $false
    $script:Requests.Clear(); $script:Replies.Clear()
}
function Enqueue-Query { $script:Replies.Enqueue((Reply 200 '{"code":"000","data":{"productModel":"DS-TEST","qaCheckResult":"server"}}')) }
New-Case 'success'; Enqueue-Query
$script:Replies.Enqueue((Reply 200 '{"code":"000","data":{"rmaId":"TEST-RMA"}}'))
$r = Invoke-SubmitOne 'TEST' 'fake-offline-token' $fixed
Assert ($r.Success -and (Read-Records)['TEST'] -eq '成功') 'successful submission journaled'
foreach ($case in @(@('timeout', 0, ''), @('http500', 500, '{"code":"000"}'), @('html', 200, '<html/>'), @('empty', 200, ''))) {
    New-Case $case[0]; Enqueue-Query; $script:Replies.Enqueue((Reply $case[1] $case[2]))
    $r = Invoke-SubmitOne 'TEST' 'fake-offline-token' $fixed
    Assert ($r.State -eq 'unknown' -and (Read-Records)['TEST'] -match '待核对') ($case[0] + ' cannot enable replay')
    Assert ($script:Requests.Count -eq 2) 'no automatic retry of submission'
}
New-Case 'auth-query'; $script:Replies.Enqueue((Reply 200 '{"code":"003"}'))
$r = Invoke-SubmitOne 'TEST' 'fake-offline-token' $fixed
Assert ($r.State -eq 'auth' -and $script:Requests.Count -eq 1) 'expired query never submits'
New-Case 'auth-submit'; Enqueue-Query; $script:Replies.Enqueue((Reply 200 '{"code":"013"}'))
$r = Invoke-SubmitOne 'TEST' 'fake-offline-token' $fixed
Assert ($r.State -eq 'auth' -and (Read-Records)['TEST'] -match '^失败') 'explicit auth rejection finalizes pending attempt'
New-Case 'reject'; Enqueue-Query; $script:Replies.Enqueue((Reply 200 '{"code":"999","msg":"业务拒绝"}'))
$r = Invoke-SubmitOne 'TEST' 'fake-offline-token' $fixed
Assert ($r.State -eq 'failed' -and (Read-Records)['TEST'] -match '^失败') 'business rejection recorded'
New-Case 'stop'; Enqueue-Query; $script:StopOnQuery = $true
$r = Invoke-SubmitOne 'TEST' 'fake-offline-token' $fixed
Assert ($r.State -eq 'stopped' -and $script:Requests.Count -eq 1 -and -not (Test-Path $script:RecPath)) 'Stop during query prevents submission'
New-Case 'journal-locked'; Enqueue-Query
$lock = New-Object IO.FileStream($script:RecPath, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { Assert-Throws { Invoke-SubmitOne 'TEST' 'fake-offline-token' $fixed } 'unwritable journal blocks submission' }
finally { $lock.Dispose() }
Assert ($script:Requests.Count -eq 1) 'no POST when intent cannot be persisted'
New-Case 'invalid-header'
[IO.File]::WriteAllText($script:RecPath, 'wrong,header')
Assert-Throws { Read-Records } 'broken journal fails closed'
# This runs only the local URL guard, before networking.
Assert-Throws { & $script:RealPost 'https://example.invalid/' 'fake' '{}' } 'token cannot be sent to another origin'
Write-Output "PASS: $script:Count assertions. All requests mocked; no RMA created."
