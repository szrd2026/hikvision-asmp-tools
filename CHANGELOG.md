# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.2.0] - 2026-11-21

- Recreate the embedded browser page on retry after renderer termination and report the failure separately from network errors.
- Let source and native launches reuse a writable data directory through an explicit path file.
- Offer an official system-browser link and verify rendered login fields in the live smoke check.
- Report ASMP security policy refusals without treating them as expired sessions.
- Remember up to 50 recent repair customers in a searchable dropdown with persistent deletion.
- Preserve the selected city and district when the operator reselects the same parent region.
- Finish the batch immediately after the last device and report authentication expiry during fault-option loading.
- Show a settings save error when the configuration directory cannot be created.
- Distinguish lock-file permission and filesystem errors from an already-running instance.
- Support an explicit portable-mode marker for native packages with data beside the executable; retain the --data-dir override.

## [2.1.0] - 2026-10-31

- Expose the previously fixed return method in the form; keep header/detail `isSend` values consistent.
- Support return to the customer with required province/city/district/address and official cascading region choices.
- Autosave settings after editing, show save status, and restore all registration fields on restart.
- Add an editable fault-description dropdown ranked by successful device registrations, with persistent deletion.
- Count confirmed successes and manual reconciliations atomically with the submission record; exclude failed, uncertain, skipped and query-only attempts.
- Upgrade the SQLite schema while preserving existing registration states; retain the old return-to-point default for existing configurations.
- Add regression coverage for request mapping, autosave failures, restart persistence, region selection and description history.

## [2.0.0] - 2026-10-31

- Rewrite the desktop application in Python, PySide6 and QtWebEngine for Windows, Linux and macOS.
- Replace CSV-based submission control with transactional SQLite attempts and audit events.
- Add query-only operation, per-serial result tables, record search/export and manual reconciliation.
- Move all HTTP work to Qt worker threads; retain durable intent and no automatic POST replay.
- Migrate legacy settings/CSV, hide session tokens and preserve the original configuration scope.
- Add native packaging, frozen Chromium smoke checks and a four-target CI build matrix.
- Preserve the old Windows implementation under `legacy/powershell`.
- Publish Chinese/English entry documentation plus installation, migration, architecture and contribution guides.
- Keep ambiguous legacy failures unresolved and isolate Windows build dependency lookup from unrelated host DLLs.

## [1.1.0] - 2026-10-30

Local development snapshot; not published as a separate GitHub release.

- Add official ASMP sign-in with an InPrivate WebView2 window and automatic session-token capture.
- Check login before each batch; detect business codes 003/013 and HTTP 401/403.
- Add durable submission intent, uncertain-outcome protection, batch deduplication and a single-instance lock.
- Preserve historical successes and server-derived product, QA and accessory fields.
- Keep the interface responsive during requests and delay, and honor Stop after detail lookup.
- Validate configuration, account capabilities, product exchange rules and HTTP response status.
- Remove plaintext token persistence and complete request/response logging; migrate old configuration.
- Add offline regression tests, browser smoke test and updated portable packaging.

## [1.0.0] - 2026-10-30

### Added

- Initial public release of the Hikvision ASMP Submit Tool.
- Bulk serial-number input with newline, comma and semicolon separators.
- Automatic RMA detail lookup through `getRmaDetailBySerial`.
- Automatic `setNewRma` payload assembly and submission.
- Configurable repair client, contact, phone number, fault type, fault
  description, deal type, repair mode and request interval.
- Duplicate-submission guard backed by `submit_records.csv`.
- Live in-window log, per-run log files and one-click access to logs and
  records.
- Portable ZIP release with a SHA-256 checksum file.

### Security

- Removed all credentials and personal data from the published source.
- Replaced the previous operator-specific defaults with clearly marked sample
  values.
- Restricted outbound HTTPS connections to TLS 1.2.
- Added `.gitignore` rules for local configuration, logs, records and build
  artifacts.

### Notes

- The application depends on Hikvision ASMP web endpoints that are not part of
  a public, versioned API. Endpoint or payload changes on the server side may
  require a client update.

[2.2.0]: https://github.com/szrd2026/hikvision-asmp-tools/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/szrd2026/hikvision-asmp-tools/compare/v2.0.0...v2.1.0
