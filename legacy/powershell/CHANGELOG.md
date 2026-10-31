# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-10-30

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
