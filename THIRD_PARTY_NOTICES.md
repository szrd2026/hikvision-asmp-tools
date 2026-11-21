# Third-party components

The application source is MIT licensed. Bundled third-party components retain their own licenses.

- Qt for Python / PySide6, Shiboken and Qt libraries: open-source LGPLv3 / GPL alternatives and third-party notices as supplied by the Qt Project. Source: https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://code.qt.io/cgit/qt/ .
- HTTPX, HTTPCore, AnyIO, h11, IDNA and typing_extensions: their upstream licenses are included in `third-party-licenses`.
- Certifi: Mozilla Public License 2.0, including the CA certificate bundle's notices.
- PyInstaller bootloader: GPL with the PyInstaller bootloader exception. Application licensing is governed by the application and bundled libraries' own terms.

The native build includes the installed distributions' license files and a `versions.json` manifest under `_internal/third-party-licenses` (or the corresponding macOS Resources directory). Additional Qt open-source license texts are included there. Library binaries are dynamically linked and remain separate in the directory-based distribution. This repository includes build scripts and exact Python dependency versions so the application can be rebuilt with replacement libraries.

The source launcher does not depend on Microsoft WebView2, .NET or PowerShell. Historical v1 artifacts under `legacy/` are excluded from the Python native package.
