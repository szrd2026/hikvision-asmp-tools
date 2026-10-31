"""Create a project-local Python environment; never modifies the system Python."""
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    raise SystemExit("需要 Python 3.11 或以上版本")
root = Path(__file__).resolve().parent
venv = root / ".venv"
if not venv.exists():
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
subprocess.run([str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")], check=True)
print("依赖已安装。Windows 双击 Start-Submit.bat，macOS 双击 Start-Submit.command，Linux 执行 bash Start-Submit.sh。")
