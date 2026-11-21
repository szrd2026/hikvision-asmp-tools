"""Keep frozen startup tracebacks available only during explicit smoke tests."""
import sys
from pathlib import Path

if "--smoke-test" in sys.argv and "--data-dir" in sys.argv:
    index = sys.argv.index("--data-dir") + 1
    if index < len(sys.argv):
        directory = Path(sys.argv[index]).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        _smoke_stream = (directory / "smoke-console.log").open("w", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = _smoke_stream
        if sys.stderr is None:
            sys.stderr = _smoke_stream
