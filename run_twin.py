"""
GridNest Root Runner.
Dispatches execution to the self-contained digital twin engine in frontend/run_twin.py.
"""
import os
import sys
import subprocess
from pathlib import Path

if __name__ == "__main__":
    frontend_dir = Path(__file__).resolve().parent / "frontend"
    target_script = frontend_dir / "run_twin.py"
    
    if not target_script.exists():
        print(f"Error: {target_script} not found.")
        sys.exit(1)
        
    cmd = [sys.executable, str(target_script)] + sys.argv[1:]
    sys.exit(subprocess.call(cmd, cwd=str(frontend_dir)))
