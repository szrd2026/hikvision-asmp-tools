#!/usr/bin/env bash
set -eu
APP_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
bash "$APP_ROOT/Start-Submit.sh" "$@"
