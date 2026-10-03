"""
GridNest Virtual IoT Simulator Root Runner.
Dispatches execution to the self-contained IoT engine in frontend/iot/iot_simulator.py.
"""
import sys
import subprocess
from pathlib import Path

if __name__ == "__main__":
    frontend_dir = Path(__file__).resolve().parent / "frontend"
    target_script = frontend_dir / "iot" / "iot_simulator.py"

    if not target_script.exists():
        print(f"Error: {target_script} not found.")
        sys.exit(1)

    cmd = [sys.executable, str(target_script)] + sys.argv[1:]
    sys.exit(subprocess.call(cmd, cwd=str(frontend_dir)))
