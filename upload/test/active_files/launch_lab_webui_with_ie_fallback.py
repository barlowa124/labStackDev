"""
Launch Lab WebUI with IE/legacy browser fallback.
- Router on port 8502: detects browser, serves IE fallback or redirects to Streamlit
- Streamlit on port 8503: full dashboard for modern browsers
- Auto-installs Flask if missing; auto-opens browser.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
STREAMLIT_PORT = 8503
ROUTER_PORT = 8502


def ensure_flask(python_exe: str) -> bool:
    """Install Flask if not present. Returns True if Flask is available."""
    try:
        import flask
        return True
    except ImportError:
        pass
    print("Installing Flask for IE fallback...")
    r = subprocess.run(
        [python_exe, "-m", "pip", "install", "flask", "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print("Warning: Flask install failed. IE fallback disabled.")
        return False
    return True


def find_free_port(start: int, end: int = 8600) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port in {start}-{end}")


def main():
    python_exe = sys.executable
    for venv in [".venv", ".venv311", ".venv_caption"]:
        exe = ROOT / venv / "Scripts" / "python.exe"
        if exe.exists():
            python_exe = str(exe)
            break

    # Ensure Streamlit port is free
    streamlit_port = STREAMLIT_PORT
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", streamlit_port))
    except OSError:
        streamlit_port = find_free_port(STREAMLIT_PORT + 1)
        print(f"Port {STREAMLIT_PORT} busy, using {streamlit_port} for Streamlit")

    env = os.environ.copy()
    env["LAB_STREAMLIT_PORT"] = str(streamlit_port)

    # Ensure Flask is installed
    ensure_flask(python_exe)

    # Start Streamlit in background
    streamlit_cmd = [
        python_exe, "-m", "streamlit", "run", str(ROOT / "lab_webui.py"),
        "--server.headless", "true", "--server.port", str(streamlit_port),
    ]
    subprocess.Popen(streamlit_cmd, cwd=str(ROOT), env=env)

    time.sleep(2)  # Let Streamlit start

    # Open browser for user
    try:
        webbrowser.open(f"http://127.0.0.1:{ROUTER_PORT}")
    except Exception:
        pass

    # Start router (foreground) with Streamlit port in env
    router_mod = ROOT / "lab_webui_router.py"
    env["LAB_STREAMLIT_PORT"] = str(streamlit_port)
    try:
        os.execve(python_exe, [python_exe, str(router_mod)], env)
    except Exception as e:
        print(f"Router failed ({e}). Opening Streamlit directly on port {ROUTER_PORT}.")
        subprocess.run([
            python_exe, "-m", "streamlit", "run", str(ROOT / "lab_webui.py"),
            "--server.headless", "true", "--server.port", str(ROUTER_PORT),
        ], cwd=str(ROOT))


if __name__ == "__main__":
    main()
