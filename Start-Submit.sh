#!/usr/bin/env bash
set -eu
APP_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -x "$APP_ROOT/.venv/bin/python" ]; then
    exec "$APP_ROOT/.venv/bin/python" "$APP_ROOT/run.py" "$@"
fi
printf '%s\n' '请先安装 Python 3.11+，然后在此目录执行：python3 setup_env.py'
exit 1
