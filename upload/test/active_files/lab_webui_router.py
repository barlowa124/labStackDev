"""
Lab WebUI Router: Detects legacy browsers (e.g. Internet Explorer) and serves
a plain HTML fallback. Modern browsers are redirected to the Streamlit app.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Flask is optional; router can run without it if we use a simpler approach
try:
    from flask import Flask, redirect, request, render_template_string
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
STREAMLIT_PORT = int(os.environ.get("LAB_STREAMLIT_PORT", "8503"))
ROUTER_PORT = 8502

# User-Agent patterns for legacy browsers (IE, old Edge)
LEGACY_UA_PATTERNS = [
    r"MSIE\s+\d",           # Internet Explorer
    r"Trident/",             # IE 11
    r"Edge/\d+\.\d+\s+Edge", # Old Edge (pre-Chromium)
]


def is_legacy_browser(user_agent: str) -> bool:
    if not user_agent:
        return False
    ua = user_agent.strip()
    for pat in LEGACY_UA_PATTERNS:
        if re.search(pat, ua, re.I):
            return True
    return False


IE_FALLBACK_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lab Dashboard (Legacy Browser)</title>
<style>
body { font-family: Arial, sans-serif; margin: 20px; max-width: 800px; }
h1 { color: #333; }
p.note { background: #f0f0f0; padding: 10px; border-left: 4px solid #666; }
form { margin: 15px 0; }
input[type="submit"] { padding: 8px 16px; margin: 4px; cursor: pointer; }
.result { background: #f9f9f9; padding: 12px; margin: 10px 0; white-space: pre-wrap; font-size: 12px; }
.success { border-left: 4px solid green; }
.error { border-left: 4px solid red; }
</style>
</head>
<body>
<h1>Lab Dashboard</h1>
<p class="note">You are using a legacy browser. This simplified interface works in Internet Explorer and other older browsers.</p>

<h2>Guided Workflow</h2>
<form method="post" action="/run/daily_qc">
  <input type="submit" value="Run Daily QC" />
</form>
<form method="post" action="/run/readiness">
  <input type="submit" value="Compute Readiness" />
</form>
<form method="post" action="/run/eln_export">
  <input type="submit" value="Export ELN/LIMS Package" />
</form>

<h2>Weekly Tasks</h2>
<form method="post" action="/run/weekly_summary">
  <input type="submit" value="Generate Weekly PI Summary" />
</form>
<form method="post" action="/run/drift_suite">
  <input type="submit" value="Run Benchmark Drift Suite" />
</form>
<form method="post" action="/run/telemetry">
  <input type="submit" value="Export Telemetry" />
</form>

<h2>METAFlux</h2>
<form method="post" action="/run/metaflux">
  <input type="submit" value="Run METAFlux Pipeline" />
</form>

{% if result %}
<div class="result {{ result_class }}">{{ result }}</div>
{% endif %}

<p style="margin-top: 30px; font-size: 12px; color: #666;">
To use the full dashboard, open this page in Chrome, Firefox, or Edge (latest).
</p>
</body>
</html>
"""


def run_command(cmd: list[str], cwd: Path) -> dict:
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return {
        "returncode": r.returncode,
        "stdout": r.stdout or "",
        "stderr": r.stderr or "",
        "ok": r.returncode == 0,
    }


def get_python_exe() -> str:
    root = PROJECT_ROOT
    for name in [".venv", ".venv311", ".venv_caption"]:
        exe = root / name / "Scripts" / "python.exe"
        if exe.exists():
            return str(exe)
    return sys.executable


def run_daily_qc(root: Path, python_exe: str) -> dict:
    cfg = root / "config.validation_ops.yaml"
    if not cfg.exists():
        cfg = root / "config.example.yaml"
    cmd = [python_exe, str(root / "run_pipeline.py"), "--config", str(cfg)]
    return run_command(cmd, root)


def run_readiness(root: Path, python_exe: str) -> dict:
    run_dirs = sorted(root.glob("output_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    records = (run_dirs[0] / "records.csv") if run_dirs else (root / "output_caption_validation_full" / "records.csv")
    if not records.exists():
        return {"ok": False, "stdout": "", "stderr": "records.csv not found. Run Daily QC first."}
    try:
        from lab_ops import compute_sample_readiness
        import pandas as pd
        df = pd.read_csv(records)
        ready = compute_sample_readiness(df)
        if "sample_readiness_status" in ready.columns:
            summary = ready["sample_readiness_status"].value_counts()
            out = f"Readiness computed. Ready: {summary.get('ready', 0)}, Review: {summary.get('review', 0)}, Hold: {summary.get('hold', 0)}"
        else:
            out = f"Readiness computed. {len(ready)} records."
        return {"ok": True, "stdout": out, "stderr": ""}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e)}


def run_eln_export(root: Path, python_exe: str) -> dict:
    run_dir = root / "output_caption_validation_full"
    if not run_dir.exists():
        run_dirs = sorted(root.glob("output_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        run_dir = run_dirs[0] if run_dirs else run_dir
    out_dir = root / "eln_packages"
    cmd = [python_exe, str(root / "export_eln_lims_package.py"), "--run-dir", str(run_dir), "--out-dir", str(out_dir)]
    return run_command(cmd, root)


def run_weekly_summary(root: Path, python_exe: str) -> dict:
    out_md = str(root / "weekly_pi_summary.md")
    cmd = [python_exe, str(root / "generate_weekly_pi_summary.py"), "--runs-root", str(root), "--pattern", "output_*", "--output", out_md]
    return run_command(cmd, root)


def run_drift_suite(root: Path, python_exe: str) -> dict:
    cmd = [python_exe, str(root / "run_benchmark_suite.py"), "--python", python_exe, "--project-root", str(root)]
    return run_command(cmd, root)


def run_telemetry(root: Path, python_exe: str) -> dict:
    team_md = str(root / "telemetry_team_report.md")
    ai_json = str(root / "telemetry_ai_report.json")
    cmd = [python_exe, str(root / "export_telemetry_reports.py"), "--runs-root", str(root), "--team-output", team_md, "--ai-output", ai_json, "--pattern", "output_*", "--window-days", "30"]
    return run_command(cmd, root)


def get_rscript_exe() -> str:
    rscript = shutil.which("Rscript")
    if rscript:
        return rscript
    for base in [Path("C:/Program Files/R"), Path.home() / "AppData/Local/Programs/R"]:
        if base.exists():
            for sub in base.glob("R-*/bin/x64/Rscript.exe"):
                return str(sub)
    return "Rscript"


def run_metaflux(root: Path, python_exe: str) -> dict:
    docs = Path.home() / "Documents"
    cfg_path = docs / "metaflux_config.example.yaml"
    r_script = docs / "metaflux_pipeline_refactored.R"
    if not cfg_path.exists():
        return {"ok": False, "stdout": "", "stderr": f"Config not found: {cfg_path}"}
    if not r_script.exists():
        return {"ok": False, "stdout": "", "stderr": f"R script not found: {r_script}"}
    import yaml
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    proj = Path(cfg.get("paths", {}).get("project_root", str(docs)))
    out_dir = proj / "runs" / f"webui_ie_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg.copy()
    cfg.setdefault("output", {})["output_dir"] = str(out_dir)
    runtime_cfg = docs / "_tmp_metaflux_ie_runtime_config.yaml"
    runtime_cfg.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    rscript_exe = get_rscript_exe()
    cmd = [rscript_exe, str(r_script), str(runtime_cfg)]
    r = run_command(cmd, docs)
    if r.get("ok"):
        r["stdout"] = (r.get("stdout") or "").strip() + f"\n\nOutputs: {out_dir}"
    return r


def main():
    if not HAS_FLASK:
        print("Flask required for IE fallback. Install: pip install flask")
        sys.exit(1)

    app = Flask(__name__)
    python_exe = get_python_exe()

    @app.route("/")
    def index():
        ua = request.headers.get("User-Agent", "")
        if is_legacy_browser(ua):
            return render_template_string(IE_FALLBACK_HTML, result=None, result_class="")
        return redirect(f"http://127.0.0.1:{STREAMLIT_PORT}", code=302)

    @app.route("/run/<action>", methods=["POST"])
    def run_action(action):
        ua = request.headers.get("User-Agent", "")
        if not is_legacy_browser(ua):
            return redirect(f"http://127.0.0.1:{STREAMLIT_PORT}", code=302)

        handlers = {
            "daily_qc": run_daily_qc,
            "readiness": run_readiness,
            "eln_export": run_eln_export,
            "weekly_summary": run_weekly_summary,
            "drift_suite": run_drift_suite,
            "telemetry": run_telemetry,
            "metaflux": run_metaflux,
        }
        handler = handlers.get(action)
        if not handler:
            return render_template_string(IE_FALLBACK_HTML, result=f"Unknown action: {action}", result_class="error")

        try:
            r = handler(PROJECT_ROOT, python_exe)
            out = (r.get("stdout") or "").strip()
            err = (r.get("stderr") or "").strip()
            combined = (out + "\n" + err).strip() if (out or err) else f"Exit code: {r.get('returncode', '?')}"
            cls = "success" if r.get("ok") else "error"
        except Exception as e:
            combined = str(e)
            cls = "error"

        return render_template_string(IE_FALLBACK_HTML, result=combined, result_class=cls)

    print(f"Lab WebUI Router: http://127.0.0.1:{ROUTER_PORT}")
    print(f"  Legacy browsers (IE) -> plain HTML fallback")
    print(f"  Modern browsers -> redirect to Streamlit on port {STREAMLIT_PORT}")
    app.run(host="127.0.0.1", port=ROUTER_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
