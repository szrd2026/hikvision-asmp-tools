# v1.0.0 · Initial public release

**Release date:** 2026-10-30

A portable Windows utility for batch RMA registration on Hikvision ASMP.
Paste serial numbers from Excel, review the live log, and let the tool perform
the detail lookup and `setNewRma` submission for each unit.

## Highlights / 亮点

- Bulk serial-number input from Excel/WPS.
- Automatic ASMP detail lookup and RMA payload assembly.
- Configurable repair client, contact, phone, fault information and request
  interval.
- Duplicate-submission guard based on local success records.
- Live log plus per-run log files and CSV records.
- No installer, no administrator rights and no third-party PowerShell modules.
- TLS 1.2-only outbound HTTPS.

## Added / 新增

- `ASMPSubmitTool.ps1` — WinForms desktop application.
- `Start-Submit.bat` — one-click Windows launcher.
- `submit_config.example.json` — sanitized configuration template.
- `build.ps1` — reproducible portable ZIP and SHA-256 builder.
- English README with a Chinese quick-start section.
- MIT license and initial changelog.

## Fixed / 修复

- Not applicable; this is the first public release.

## Security / 安全

- Removed all previously hard-coded credentials and operator-specific personal
  data from the published source.
- Replaced real defaults with clearly marked sample values.
- Added `.gitignore` rules for local tokens, logs, records and build output.
- Limited outbound HTTPS to TLS 1.2.

## Known issues / 已知问题

- The application relies on Hikvision ASMP web endpoints that are not a public,
  versioned API. Server-side changes may require a client update.
- Access tokens expire. There is no automatic refresh; copy a new token when
  the tool reports `notLogin`.
- The release is not code-signed. See the SmartScreen note below.
- Logs and `submit_records.csv` can contain serial numbers and customer
  information. They are excluded from Git, but users must protect them locally.
- The user interface is currently Chinese-only.
- Live submission was not exercised during packaging verification because no
  production token was used. GUI startup, configuration loading, package
  extraction and script parsing were verified locally.

## Assets / 附件说明

| Asset | Purpose | Requirements |
| --- | --- | --- |
| `Hikvision-ASMP-Submit-v1.0.0-win64.zip` | Portable application package. Extract and run `Start-Submit.bat`. | Windows 10/11 x64, Windows PowerShell 5.1, ASMP account, HTTPS access to `asmp.hikvision.com` |
| `checksums.txt` | SHA-256 checksum for the ZIP. | Any text editor or `Get-FileHash` |

**System requirements:** Windows 10 or Windows 11 (x64), Windows PowerShell 5.1
(built in), an authorized Hikvision ASMP account, and network access to
`https://asmp.hikvision.com`. Administrator rights are not required.

## SHA-256

```text
049d42c52df3ae68b904f32790cd5f55da3be9c41db785c28261aef4d51d7c4d  Hikvision-ASMP-Submit-v1.0.0-win64.zip
```

File size: **35,583 bytes**.

Verify after download:

```powershell
Get-FileHash .\Hikvision-ASMP-Submit-v1.0.0-win64.zip -Algorithm SHA256
```

## Installation / 安装

1. Download the ZIP from this release.
2. Extract it to a local folder. Do not run it from inside the archive.
3. Double-click `Start-Submit.bat`.
4. Copy a fresh `accesstoken` from the ASMP web portal:
   `F12` → **Network** → any ASMP request → **Request Headers** → `accesstoken`.
5. Replace the sample repair information with your own data, paste the serial
   numbers and start the batch.

## SmartScreen note / 签名提示

This release is not code-signed. **未签名 exe 会被 SmartScreen 提示未知发布者，
属正常现象。** This version is distributed as a ZIP with batch/PowerShell
files rather than an exe; browsers or Windows may still mark the downloaded ZIP
as coming from the internet. Verify the SHA-256 above, then use
**Properties → Unblock** before extracting if necessary.

## Disclaimer / 免责声明

This is an unofficial project and is not affiliated with, endorsed by, or
supported by Hikvision. Use it only with accounts you are authorized to
operate, and comply with Hikvision's terms, your organization's policies and
applicable law. The software is provided under the MIT license, without
warranty.
