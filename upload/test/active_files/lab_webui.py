from __future__ import annotations

import json
import hashlib
import html
import math
import os
from datetime import datetime
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
import urllib.request
import urllib.error
import uuid

import pandas as pd
import streamlit as st
import yaml
import streamlit.components.v1 as components
try:
    import plotly.graph_objects as go
except Exception:
    go = None

try:
    from lab_collab import (
        add_comment,
        add_proposal,
        default_db_path,
        init_collab_db,
        list_activity,
        list_comments,
        list_proposals,
        log_edit,
        log_view,
        review_proposal,
    )
    HAS_LAB_COLLAB = True
except ImportError:
    HAS_LAB_COLLAB = False

    def _noop(*a, **k):
        pass

    add_comment = add_proposal = init_collab_db = list_activity = list_comments = list_proposals = log_edit = log_view = review_proposal = _noop

    def default_db_path(root: Path) -> Path:
        return root / "lab_collab.db"

from lab_ops import compute_sample_readiness
from python_compat import require_supported_python


PROJECT_ROOT = Path(__file__).parent.resolve()
PREFERRED_CELLMEDIA_RUN = "output_caption_validation_full"

LAB_LANGUAGE_MAP = {
    "Daily QC": "Daily Microscopy Image QC",
    "Drift & Promotion": "Weekly Drift Check & Model Promotion",
    "Weekly PI Summary": "Weekly PI Summary",
    "ELN/LIMS Export": "ELN/LIMS Package Export",
    "Readiness": "Readiness Gate",
    "Run Daily QC Pipeline": "Run Daily Microscopy Image QC",
    "Run Daily QC": "Run Daily Microscopy Image QC",
    "Start Daily QC": "Start Daily Microscopy Image QC",
    "Drift Evaluation": "Caption Drift Comparison",
    "Run Drift Evaluation": "Run Caption Drift Comparison",
    "Run Benchmark Drift Suite": "Run Weekly Drift Check",
    "Run Promotion Decision": "Run Model Promotion Policy Check",
    "Max acceptable mean drift": "Max acceptable mean drift score",
    "Generate Weekly PI Summary": "Generate Weekly PI Summary",
    "Generate Weekly Summary": "Generate Weekly PI Summary",
    "Export ELN/LIMS Package": "Export ELN/LIMS Package",
    "Export Package": "Export ELN/LIMS Package",
    "Sample Readiness Triage": "Sample Readiness Gate",
    "Compute Readiness": "Compute Readiness Gate",
    "records.csv path": "records.csv path",
    "Guided Workflow (First Run)": "Guided In-Lab Workflow",
    "Optional Weekly Tasks": "Optional Weekly Checks",
    "Promotion decision output JSON": "Model promotion decision output JSON",
    "Runs root folder": "Runs root folder",
    "Run directory glob pattern": "Run directory glob pattern",
    "Output markdown file": "Weekly summary output markdown file",
    "Run output folder": "Run output folder",
    "Package destination folder": "ELN/LIMS package destination folder",
    "Bug Reporter": "Lab Bug Reporter",
    "Save Bug Report": "Save Bug Report",
}


def ui_text(use_lab_language: bool, text: str) -> str:
    if not use_lab_language:
        return text
    return LAB_LANGUAGE_MAP.get(text, text)


def run_command(command: list[str], cwd: Path | None = None) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=str(cwd or PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "ok": result.returncode == 0,
    }


def api_post_json(base_url: str, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = os.environ.get("LAB_API_TOKEN", "").strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = base_url.rstrip("/") + endpoint
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return {"ok": True, "data": json.loads(body) if body else {}}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            body = str(exc)
        return {"ok": False, "error": f"HTTP {exc.code}: {body}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def api_get_json(
    base_url: str, endpoint: str, query: dict[str, Any] | None = None
) -> dict[str, Any]:
    token = os.environ.get("LAB_API_TOKEN", "").strip()
    qs = f"?{urlencode(query or {})}" if query else ""
    url = base_url.rstrip("/") + endpoint + qs
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return {"ok": True, "data": json.loads(body) if body else {}}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            body = str(exc)
        return {"ok": False, "error": f"HTTP {exc.code}: {body}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def append_webui_telemetry_event(root: Path, event_type: str, diagnosis: str, details: dict[str, Any] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    events_path = root / "webui_telemetry.jsonl"
    summary_path = root / "webui_telemetry_summary.json"

    now_local = datetime.now().isoformat(timespec="seconds")
    now_utc = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    payload = {
        "timestamp_local": now_local,
        "timestamp_utc": now_utc,
        "component": "lab_webui",
        "event_type": event_type,
        "diagnosis": diagnosis,
        "details": details or {},
    }

    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    total = 0
    counts: dict[str, int] = {}
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            total += 1
            et = str(row.get("event_type", "unknown"))
            counts[et] = counts.get(et, 0) + 1
    except Exception:
        pass

    summary = {
        "generated_at_local": now_local,
        "generated_at_utc": now_utc,
        "component": "lab_webui",
        "event_count": total,
        "event_type_counts": counts,
        "last_event": payload,
        "files": {
            "events_jsonl": str(events_path),
            "summary_json": str(summary_path),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return events_path


def _scan_automation_processes() -> list[str]:
    candidates = ["chromedriver", "msedgedriver", "geckodriver", "selenium", "playwright"]
    found: set[str] = set()
    try:
        if platform.system().strip().lower() == "windows":
            result = subprocess.run(["tasklist"], capture_output=True, text=True)
            hay = (result.stdout or "").lower()
        else:
            result = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True)
            hay = (result.stdout or "").lower()
        for name in candidates:
            if name in hay:
                found.add(name)
    except Exception:
        return []
    return sorted(found)


def collect_host_control_diagnostics() -> dict[str, Any]:
    env = os.environ
    session_name = str(env.get("SESSIONNAME", ""))
    is_windows = platform.system().strip().lower() == "windows"

    remote_signals = {
        "ssh_connection": bool(env.get("SSH_CONNECTION")),
        "ssh_client": bool(env.get("SSH_CLIENT")),
        "ssh_tty": bool(env.get("SSH_TTY")),
        "rdp_session": bool(is_windows and session_name.upper().startswith("RDP")),
        "vscode_remote": bool(env.get("VSCODE_IPC_HOOK_CLI") or env.get("VSCODE_GIT_IPC_HANDLE")),
    }
    remote_detected = any(remote_signals.values())

    selenium_env = {
        "SELENIUM_REMOTE_URL": bool(env.get("SELENIUM_REMOTE_URL")),
        "WEBDRIVER_REMOTE_SESSIONID": bool(env.get("WEBDRIVER_REMOTE_SESSIONID")),
    }
    automation_processes = _scan_automation_processes()
    selenium_like_control = any(selenium_env.values()) or len(automation_processes) > 0

    return {
        "ui_focus_state": "unknown_server_side",
        "ui_minimized_state": "unknown_server_side",
        "focus_detection_note": "Browser focus/minimized state is not directly observable from server-side Streamlit runtime.",
        "selenium_like_control_detected": selenium_like_control,
        "selenium_env_signals": selenium_env,
        "automation_processes": automation_processes,
        "remote_connection_detected": remote_detected,
        "remote_signals": remote_signals,
        "session_name": session_name,
    }


def load_webui_telemetry_events(root: Path) -> list[dict[str, Any]]:
    events_path = root / "webui_telemetry.jsonl"
    if not events_path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def render_webui_telemetry_panel(root: Path) -> None:
    events = load_webui_telemetry_events(root)

    diagnosis_friendly = {
        "bridge_sync_success": "New files pulled from Google Drive successfully",
        "bridge_detected_new_images": "New images detected and pipeline started",
        "bridge_no_new_images": "No new images found (system is idle)",
        "bridge_test_ok": "Bridge test ran successfully",
        "bridge_test_failed": "Bridge test failed (needs attention)",
    }

    detail_key_friendly = {
        "timestamp_local": "Local Time",
        "timestamp_utc": "UTC Time",
        "component": "Component",
        "event_type": "Check Type",
        "diagnosis": "Diagnosis",
        "details": "Details",
        "host_platform": "Computer Type",
        "returncode": "Return Code",
        "ui_focus_state": "In Focus",
        "ui_minimized_state": "Minimized",
        "focus_detection_note": "Focus Detection Note",
        "selenium_like_control_detected": "Selenium Control",
        "selenium_env_signals": "Selenium Environment Signals",
        "automation_processes": "Automation Processes",
        "remote_connection_detected": "Remote Connection",
        "remote_signals": "Remote Signals",
        "session_name": "Session Name",
        "ssh_connection": "SSH Connection",
        "ssh_client": "SSH Client",
        "ssh_tty": "SSH TTY",
        "rdp_session": "RDP Session",
        "vscode_remote": "VS Code Remote",
    }

    special_value_friendly = {
        "unknown_server_side": "Not available from server-side app",
    }

    def _friendly_key(key: str) -> str:
        if key in detail_key_friendly:
            return detail_key_friendly[key]
        pretty = str(key).replace("_", " ").strip()
        return " ".join(part.capitalize() for part in pretty.split())

    def _friendly_scalar(parent_key: str, value: Any) -> Any:
        if isinstance(value, str):
            if parent_key == "diagnosis":
                return diagnosis_friendly.get(value, value)
            return special_value_friendly.get(value, value)
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return value

    def _translate_payload(payload: Any, parent_key: str = "") -> Any:
        if isinstance(payload, dict):
            translated: dict[str, Any] = {}
            for raw_key, raw_value in payload.items():
                friendly_key = _friendly_key(str(raw_key))
                translated[friendly_key] = _translate_payload(raw_value, str(raw_key))
            return translated
        if isinstance(payload, list):
            return [_translate_payload(item, parent_key) for item in payload]
        return _friendly_scalar(parent_key, payload)

    st.markdown("#### Telemetry Diagnoses")
    with st.expander("Telemetry Legend (Expanded)"):
        st.markdown("Use this panel as a quick health check for automation and host conditions.")
        st.table(
            pd.DataFrame(
                [
                    {"Field": "Local time", "What it means": "When the check happened on this computer", "What to do": "Use this as your primary timestamp"},
                    {"Field": "UTC time", "What it means": "Universal time version of the same event", "What to do": "Helpful when comparing logs from different locations"},
                    {"Field": "Diagnosis", "What it means": "Human-readable result of the bridge test", "What to do": "If it says failed, run the bridge test again and review details"},
                    {"Field": "Computer type", "What it means": "Detected host OS (Windows/macOS/Linux)", "What to do": "Confirm it matches the machine you are using"},
                    {"Field": "Return code", "What it means": "`0` means success, other values indicate an error", "What to do": "If non-zero, check 'Latest diagnosis details'"},
                    {"Field": "In focus / Minimized", "What it means": "Browser focus state cannot be directly read by server-side app", "What to do": "Treat `unknown_server_side` as expected"},
                    {"Field": "Selenium control", "What it means": "Whether automation-like control signals were detected", "What to do": "If True unexpectedly, verify no unintended automation is running"},
                    {"Field": "Remote connection", "What it means": "Whether signs of remote session were detected", "What to do": "If True, note that checks were run over remote access"},
                ]
            ),
            width="stretch",
        )

        st.markdown("**Diagnosis labels used in this dashboard**")
        st.table(
            pd.DataFrame(
                [
                    {"System label": k, "Displayed meaning": v}
                    for k, v in diagnosis_friendly.items()
                ]
            ),
            width="stretch",
        )

    if not events:
        st.caption("No web UI telemetry events logged yet.")
        return

    bridge_events = [e for e in events if str(e.get("event_type", "")) == "bridge_test_once"]
    last = events[-1]

    c1, c2, c3 = st.columns(3)
    c1.metric("Total events", len(events))
    c2.metric("Bridge tests", len(bridge_events))
    c3.metric("Last diagnosis", diagnosis_friendly.get(str(last.get("diagnosis", "n/a")), str(last.get("diagnosis", "n/a"))))

    rows: list[dict[str, Any]] = []
    for event in reversed(events):
        details = event.get("details", {}) if isinstance(event.get("details"), dict) else {}
        rows.append(
            {
                "Local Time": event.get("timestamp_local", ""),
                "UTC Time": event.get("timestamp_utc", ""),
                "Check Type": event.get("event_type", ""),
                "Diagnosis": diagnosis_friendly.get(str(event.get("diagnosis", "")), str(event.get("diagnosis", ""))),
                "Computer Type": details.get("host_platform", ""),
                "Return Code": details.get("returncode", ""),
                "In Focus": details.get("ui_focus_state", ""),
                "Minimized": details.get("ui_minimized_state", ""),
                "Selenium Control": details.get("selenium_like_control_detected", ""),
                "Remote Connection": details.get("remote_connection_detected", ""),
            }
        )

    st.dataframe(pd.DataFrame(rows), width="stretch")

    with st.expander("Latest diagnosis details"):
        st.markdown("**Translated JSON (plain language)**")
        st.json(_translate_payload(last))
        st.markdown("**Raw JSON (exact system output)**")
        st.json(last)


def init_process_state() -> None:
    if "managed_processes" not in st.session_state:
        st.session_state["managed_processes"] = {}
    if "selected_process_id" not in st.session_state:
        st.session_state["selected_process_id"] = None


def start_managed_process(name: str, command: list[str], cwd: Path | None = None) -> str:
    init_process_state()
    process_id = uuid.uuid4().hex[:10]
    logs_dir = PROJECT_ROOT / ".process_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{process_id}_{re.sub(r'[^a-zA-Z0-9]+', '_', name.lower())}.log"
    log_handle = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        command,
        cwd=str(cwd or PROJECT_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    st.session_state["managed_processes"][process_id] = {
        "id": process_id,
        "name": name,
        "command": command,
        "cwd": str(cwd or PROJECT_ROOT),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "proc": proc,
        "pid": proc.pid,
        "log_path": str(log_path),
        "log_handle": log_handle,
    }
    st.session_state["selected_process_id"] = process_id
    return process_id


def poll_managed_processes() -> None:
    init_process_state()
    procs = st.session_state.get("managed_processes", {})
    for process_id, info in list(procs.items()):
        if info.get("status") != "running":
            continue
        proc = info.get("proc")
        if proc is None:
            continue
        rc = proc.poll()
        if rc is None:
            continue
        log_handle = info.get("log_handle")
        if log_handle:
            try:
                log_handle.flush()
                log_handle.close()
            except Exception:
                pass
            info["log_handle"] = None
        info["returncode"] = rc
        info["status"] = "completed" if rc == 0 else "failed"
        info["finished_at"] = datetime.now().isoformat(timespec="seconds")


def stop_managed_process(process_id: str) -> bool:
    init_process_state()
    info = st.session_state.get("managed_processes", {}).get(process_id)
    if not info:
        return False
    proc = info.get("proc")
    if proc and info.get("status") == "running":
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    log_handle = info.get("log_handle")
    if log_handle:
        try:
            log_handle.flush()
            log_handle.close()
        except Exception:
            pass
        info["log_handle"] = None
    info["status"] = "stopped"
    info["returncode"] = -15
    info["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return True


def close_process_tab(process_id: str) -> None:
    info = st.session_state.get("managed_processes", {}).get(process_id)
    if not info:
        return
    if info.get("status") == "running":
        stop_managed_process(process_id)
    st.session_state["managed_processes"].pop(process_id, None)
    if st.session_state.get("selected_process_id") == process_id:
        st.session_state["selected_process_id"] = None


def read_log_tail(log_path: str | None, max_lines: int = 120) -> str:
    if not log_path:
        return ""
    path = Path(log_path)
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return ""
    tail = lines[-max_lines:]
    return "\n".join(tail)


def _safe_parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None


def process_elapsed_text(started_at: str | None, finished_at: str | None = None) -> str:
    start_dt = _safe_parse_iso(started_at)
    if not start_dt:
        return "unknown"
    end_dt = _safe_parse_iso(finished_at) or datetime.now()
    seconds = max(0, int((end_dt - start_dt).total_seconds()))
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs}h {mins}m {secs}s"
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def clear_completed_processes() -> int:
    init_process_state()
    procs = st.session_state.get("managed_processes", {})
    removable = [pid for pid, info in procs.items() if info.get("status") != "running"]
    for pid in removable:
        info = procs.get(pid, {})
        log_handle = info.get("log_handle")
        if log_handle:
            try:
                log_handle.flush()
                log_handle.close()
            except Exception:
                pass
        procs.pop(pid, None)
    selected_id = st.session_state.get("selected_process_id")
    if selected_id and selected_id not in procs:
        st.session_state["selected_process_id"] = None
    return len(removable)


def render_process_topbar() -> None:
    poll_managed_processes()
    procs = st.session_state.get("managed_processes", {})
    selected = st.session_state.get("selected_process_id")
    selected_info = procs.get(selected) if selected else None
    running = [p for p in procs.values() if p.get("status") == "running"]

    with st.container(border=True):
        col1, col2 = st.columns([5, 1])
        with col1:
            if selected_info:
                st.markdown(
                    f"**Current Process:** {selected_info.get('name')} | status={selected_info.get('status')} | pid={selected_info.get('pid')}"
                )
                elapsed = process_elapsed_text(selected_info.get("started_at"), selected_info.get("finished_at"))
                st.caption(f"Elapsed: {elapsed}")
            else:
                st.markdown("**Current Process:** none selected")
            st.caption(f"Running now: {len(running)}")
            if running:
                running_names = ", ".join(p.get("name", "Unnamed") for p in running[:4])
                suffix = " ..." if len(running) > 4 else ""
                st.caption(f"Active: {running_names}{suffix}")
        with col2:
            stop_clicked = st.button(
                "Stop",
                key="topbar_stop_selected",
                help=mode_aware_tooltip(
                    "Stop the job you have selected right now.",
                    "Stop the currently selected running process.",
                    current_power_user_mode(),
                ),
            )
            if stop_clicked and selected_info:
                stop_managed_process(selected_info["id"])
                st.success("Selected process stopped.")
            clear_clicked = st.button(
                "Clear Done",
                key="topbar_clear_done",
                help=mode_aware_tooltip(
                    "Clear old finished jobs from this list.",
                    "Remove completed/failed/stopped process entries.",
                    current_power_user_mode(),
                ),
            )
            if clear_clicked:
                removed = clear_completed_processes()
                st.success(f"Removed {removed} finished process entr{'y' if removed == 1 else 'ies'}.")

        if selected_info:
            with st.expander("Selected process logs"):
                st.caption("Live tail of process log (refresh by interacting with app).")
                tail_text = read_log_tail(selected_info.get("log_path"))
                if tail_text:
                    st.text(tail_text)
                else:
                    st.caption("No log output yet.")


def render_process_hotbar() -> None:
    poll_managed_processes()
    procs = st.session_state.get("managed_processes", {})
    running = [p for p in procs.values() if p.get("status") == "running"]
    recent_done = [p for p in procs.values() if p.get("status") in {"completed", "failed", "stopped"}]
    recent_done = sorted(
        recent_done,
        key=lambda p: str(p.get("finished_at", p.get("started_at", ""))),
        reverse=True,
    )[:5]

    if not running and not recent_done:
        return

    st.markdown("---")
    st.markdown("### Process Hotbar")

    if running:
        st.markdown("**Running now**")
    else:
        st.caption("No active background process right now.")

    for info in running:
        c1, c2, c3 = st.columns([6, 1, 1])
        with c1:
            elapsed = process_elapsed_text(info.get("started_at"))
            if st.button(
                f"🧪 {info.get('name')} (pid {info.get('pid')}, {elapsed})",
                key=f"focus_{info['id']}",
                help=mode_aware_tooltip(
                    "Open this running job so you can watch its logs.",
                    "Focus this running process.",
                    current_power_user_mode(),
                ),
            ):
                st.session_state["selected_process_id"] = info["id"]
        with c2:
            if st.button(
                "✕",
                key=f"stop_{info['id']}",
                help=mode_aware_tooltip(
                    "Stop this running job.",
                    "Stop this running process.",
                    current_power_user_mode(),
                ),
            ):
                stop_managed_process(info["id"])
        with c3:
            if st.button(
                "🗑",
                key=f"close_{info['id']}",
                help=mode_aware_tooltip(
                    "Remove this job row from the list.",
                    "Close this process tab entry.",
                    current_power_user_mode(),
                ),
            ):
                close_process_tab(info["id"])

    if recent_done:
        st.markdown("**Recently finished**")
        for info in recent_done:
            status = info.get("status")
            status_icon = "✅" if status == "completed" else "⚠️" if status == "failed" else "⏹"
            elapsed = process_elapsed_text(info.get("started_at"), info.get("finished_at"))
            c1, c2, c3 = st.columns([6, 1, 1])
            with c1:
                if st.button(
                    f"{status_icon} {info.get('name')} ({status}, {elapsed})",
                    key=f"focus_done_{info['id']}",
                    help=mode_aware_tooltip(
                        "Open this finished job to review what happened.",
                        "Focus this finished process and inspect logs.",
                        current_power_user_mode(),
                    ),
                ):
                    st.session_state["selected_process_id"] = info["id"]
            with c2:
                st.caption(f"rc={info.get('returncode')}")
            with c3:
                if st.button(
                    "🗑",
                    key=f"close_done_{info['id']}",
                    help=mode_aware_tooltip(
                        "Remove this finished job row from the list.",
                        "Remove this finished process entry.",
                        current_power_user_mode(),
                    ),
                ):
                    close_process_tab(info["id"])


def render_hover_tooltip_label(label: str, tooltip: str) -> None:
    safe_label = html.escape(label, quote=True)
    safe_tooltip = html.escape(tooltip, quote=True)
    st.markdown(
        f"<div class='hover-tooltip-label' title='{safe_tooltip}'>{safe_label}</div>",
        unsafe_allow_html=True,
    )


def mode_aware_tooltip(streamlined_text: str, power_user_text: str, power_user_mode: bool) -> str:
    return power_user_text if power_user_mode else streamlined_text


def current_power_user_mode() -> bool:
    return st.session_state.get("mode_pref", "Streamlined (recommended)") == "In-Lab Custom"


def render_process_monitor_with_autorefresh() -> None:
    init_process_state()
    if "process_auto_refresh" not in st.session_state:
        st.session_state["process_auto_refresh"] = True

    with st.container(border=True):
        left, right = st.columns([3, 2])
        with left:
            st.markdown("#### Process Monitor")
            st.caption("Tracks active and recent background jobs.")
        with right:
            render_hover_tooltip_label(
                "Auto-refresh process monitor",
                "When enabled, process status and logs refresh automatically every few seconds.",
            )
            st.toggle(
                "Auto-refresh process monitor switch",
                key="process_auto_refresh",
                label_visibility="collapsed",
            )

    if hasattr(st, "fragment"):
        @st.fragment(run_every="3s")
        def _process_fragment() -> None:
            if st.session_state.get("process_auto_refresh", True):
                render_process_topbar()
                render_process_hotbar()
            else:
                render_process_topbar()
                render_process_hotbar()

        _process_fragment()
    else:
        render_process_topbar()
        render_process_hotbar()


def render_hotkey_bindings() -> None:
    components.html(
        """
        <script>
        const doc = window.parent.document;
        if (!doc.__labHotkeysBound) {
          doc.__labHotkeysBound = true;
          doc.addEventListener('keydown', function(e) {
            const key = (e.key || '').toLowerCase();
            if (e.ctrlKey && key === 'r') {
              e.preventDefault();
              const btn = Array.from(doc.querySelectorAll('button')).find(b => b.innerText.includes('Start Daily QC (BG)'));
              if (btn) btn.click();
            }
            if (e.ctrlKey && key === 'e') {
              e.preventDefault();
              const btn = Array.from(doc.querySelectorAll('button')).find(b => b.innerText.trim() === 'Stop');
              if (btn) btn.click();
            }
          });
        }
        </script>
        """,
        height=0,
    )


def apply_global_ui_style() -> None:
    st.markdown(
        """
        <style>
        :root {
          --lab-font: "Linux Biolinum O", "Linux Biolinum", "Biolinum", "Segoe UI", Arial, sans-serif;
        }
        html, body, [class*="css"], [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
          font-family: var(--lab-font) !important;
        }
        .hover-tooltip-label {
          display: inline-block;
          font-size: 0.95rem;
          font-weight: 600;
          margin-bottom: 0.15rem;
          cursor: help;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_shift_dashboard(root: Path, python_exe: str) -> None:
    st.markdown("### Shift Dashboard")
    with st.container(border=True):
        st.caption("One-click actions for common lab shift operations.")
        c1, c2, c3 = st.columns(3)

        with c1:
            if st.button(
                "Quick Start Daily QC (BG)",
                key="shift_quick_daily_bg",
                help=mode_aware_tooltip(
                    "Start the main quality run in the background using the default settings.",
                    "Launch Daily QC in background using config.validation_ops.yaml.",
                    current_power_user_mode(),
                ),
                width="stretch",
            ):
                cfg = root / "config.validation_ops.yaml"
                if not cfg.exists():
                    st.error(f"Config not found: {cfg}")
                else:
                    process_id = start_managed_process(
                        name="Daily QC",
                        command=[python_exe, str(root / "run_pipeline.py"), "--config", str(cfg)],
                        cwd=root,
                    )
                    st.success(f"Background process started: {process_id}")

        with c2:
            if st.button(
                "Quick Readiness Check",
                key="shift_quick_readiness",
                help=mode_aware_tooltip(
                    "Check whether the latest run is ready, needs review, or should be held.",
                    "Compute readiness from the latest run records.csv.",
                    current_power_user_mode(),
                ),
                width="stretch",
            ):
                latest = latest_run_dir(root)
                records = (latest / "records.csv") if latest else (root / "output_caption_microscopy_full_bliplarge" / "records.csv")
                readiness_preview(records)

        with c3:
            if st.button(
                "Quick Telemetry Export (BG)",
                key="shift_quick_telemetry_bg",
                help=mode_aware_tooltip(
                    "Export summary reports in the background for people and automation.",
                    "Run telemetry export in background for team markdown and AI JSON outputs.",
                    current_power_user_mode(),
                ),
                width="stretch",
            ):
                process_id = start_managed_process(
                    name="Telemetry Export",
                    command=[
                        python_exe,
                        str(root / "export_telemetry_reports.py"),
                        "--runs-root",
                        str(root),
                        "--team-output",
                        str(root / "telemetry_team_report.md"),
                        "--ai-output",
                        str(root / "telemetry_ai_report.json"),
                        "--pattern",
                        "output_*",
                        "--window-days",
                        "30",
                    ],
                    cwd=root,
                )
                st.success(f"Background process started: {process_id}")


def render_section_glance_image(title: str, emoji: str, color: str = "#1f4e79") -> None:
    svg = f"""
    <svg xmlns='http://www.w3.org/2000/svg' width='480' height='90'>
      <rect x='0' y='0' width='480' height='90' rx='12' fill='{color}' />
      <text x='20' y='56' font-size='36'>{emoji}</text>
      <text x='78' y='56' font-size='24' fill='white' font-family='Segoe UI, Arial'>{title}</text>
    </svg>
    """
    st.image(f"data:image/svg+xml;utf8,{quote(svg)}", width="stretch")


SECTION_HELP: dict[str, dict[str, str]] = {
    "Daily QC": {
        "goal": "Run microscopy QC end-to-end and produce standardized records + run status.",
        "input": "Validated config + image set (and optional spectral calibration settings).",
        "output": "records.csv, run_status.json, telemetry, and artifact folders for downstream triage.",
    },
    "Readiness": {
        "goal": "Triage samples into ready/review/hold based on quality and caption signals.",
        "input": "records.csv from the latest or selected run.",
        "output": "Readiness table with reasons and recapture guidance.",
    },
    "ELN/LIMS Export": {
        "goal": "Package handoff-ready artifacts for ELN/LIMS and audit tracking.",
        "input": "A completed run directory plus QC checklist confirmations.",
        "output": "Timestamped package directory and zip.",
    },
    "Weekly + Telemetry": {
        "goal": "Generate management-facing summaries and machine-readable telemetry exports.",
        "input": "Run root + output pattern + reporting window.",
        "output": "Weekly summary markdown and telemetry markdown/json outputs.",
    },
    "Drift Evaluation": {
        "goal": "Compare model outputs and quantify caption drift before promotion decisions.",
        "input": "Baseline and candidate records.csv files.",
        "output": "Drift report + promotion decision JSON.",
    },
    "Alerts & Trends": {
        "goal": "Surface current risk signals and trend trajectories from recent runs.",
        "input": "Recent output folders and configurable alert thresholds.",
        "output": "Actionable alerts and trend plots for quality, drift, and hold rates.",
    },
    "Cell/Media Visualizations": {
        "goal": "Inspect density heatmaps/wavetables and cell/media summary metrics.",
        "input": "Run directory with records.csv and density artifact CSVs.",
        "output": "At-a-glance metrics, trend charts, heatmap grids, and wavetable profiles.",
    },
    "METAFlux": {
        "goal": "Run metabolic flux analysis from RNA-seq: pathway heatmap and nutrient boxplot.",
        "input": "RNA-seq matrix (Excel), config YAML (project_root, knockout genes, nutrients, medium).",
        "output": "pathway_heatmap.png, nutrient_flux_boxplot.png, flux CSVs, run_metadata.json, ZIP bundle.",
    },
}


OPERATOR_PROFILES = [
    "DeltaV Familiar",
    "New to Lab / No DeltaV",
]


def render_operator_walkthrough(
    profile: str,
    use_lab_language: bool,
    latest_run: Path | None,
    use_local_api: bool,
) -> None:
    with st.container(border=True):
        st.subheader("Operator Walkthrough")
        st.caption(
            f"Active profile: {profile}. This walkthrough adapts guidance for your background."
        )

        if profile == "DeltaV Familiar":
            st.markdown("#### Fast Onboarding for DeltaV Operators")
            st.write(
                "Use this app like a lightweight control-room layer: monitor status, run workflows, "
                "review alarms/quality signals, and track controlled changes."
            )
            st.table(
                pd.DataFrame(
                    [
                        {
                            "DeltaV Mental Model": "Module/Unit status",
                            "Here in this app": "System Status + Shift Dashboard + Process Monitor",
                        },
                        {
                            "DeltaV Mental Model": "Batch/sequence trigger",
                            "Here in this app": "Run Daily QC / Drift / Export buttons",
                        },
                        {
                            "DeltaV Mental Model": "Alarm/event review",
                            "Here in this app": "Alerts & Trends + Readiness hold/review flags",
                        },
                        {
                            "DeltaV Mental Model": "Change control",
                            "Here in this app": "Collaboration tab (comments, proposed edits, approvals)",
                        },
                        {
                            "DeltaV Mental Model": "Handoff records",
                            "Here in this app": "ELN/LIMS Export + Run Fingerprint + Telemetry outputs",
                        },
                    ]
                ),
                width="stretch",
            )
            st.markdown("**Suggested first 10 minutes**")
            st.write(
                "1) Check System Status and Process Monitor, 2) Run/verify Daily QC, "
                "3) Confirm Readiness, 4) Submit/approve any workflow changes in Collaboration."
            )
        else:
            st.markdown("#### Guided Onboarding for New Lab Members")
            st.write(
                "No control-system experience needed. Follow these steps in order; the app tells you what each stage produces."
            )
            st.table(
                pd.DataFrame(
                    [
                        {
                            "Step": "1) Daily QC",
                            "What you do": "Run image quality checks",
                            "Output": "records.csv + run status",
                        },
                        {
                            "Step": "2) Readiness",
                            "What you do": "Sort samples into ready/review/hold",
                            "Output": "Actionable triage table",
                        },
                        {
                            "Step": "3) ELN/LIMS Export",
                            "What you do": "Package approved run data",
                            "Output": "Submission-ready package + audit trace",
                        },
                        {
                            "Step": "4) Collaboration",
                            "What you do": "Leave notes and propose changes",
                            "Output": "Shared change history and approvals",
                        },
                    ]
                ),
                width="stretch",
            )
            st.markdown("**Suggested first 15 minutes**")
            st.write(
                "1) Stay in Streamlined mode, 2) Run Daily QC (or review latest run), "
                "3) Open Readiness and inspect hold/review rows, 4) Add a comment if anything is unclear."
            )

        st.caption(
            "Current system context: "
            + ("run detected" if latest_run else "no run detected yet")
            + f", local API {'connected' if use_local_api else 'offline'}."
        )


def render_section_help(section_key: str) -> None:
    info = SECTION_HELP.get(section_key)
    if not info:
        return
    with st.expander("What this section does"):
        st.write(f"**Goal:** {info['goal']}")
        st.write(f"**Input:** {info['input']}")
        st.write(f"**Output:** {info['output']}")


def show_command_result(title: str, result: dict[str, Any], show_logs: bool = True) -> None:
    if result["ok"]:
        st.success(f"{title} completed successfully.")
    else:
        st.error(f"{title} failed (exit code: {result['returncode']}).")

    if show_logs and result.get("stdout"):
        with st.expander(f"{title} output log"):
            st.text(result["stdout"])
    if show_logs and result.get("stderr"):
        with st.expander(f"{title} error log"):
            st.text(result["stderr"])


def parse_json_tail(stdout_text: str) -> dict[str, Any] | None:
    text = (stdout_text or "").strip()
    if not text:
        return None
    end = text.rfind("}")
    if end == -1:
        return None
    start = text.rfind("{", 0, end + 1)
    if start == -1:
        return None
    snippet = text[start : end + 1]
    try:
        data = json.loads(snippet)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def latest_run_dir(root: Path) -> Path | None:
    candidates: list[Path] = []
    for path in root.glob("output_*"):
        if path.is_dir() and (path / "records.csv").exists():
            candidates.append(path)
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def readiness_preview(records_csv: Path) -> None:
    if not records_csv.exists():
        st.error(f"records.csv not found: {records_csv}")
        return
    try:
        df = pd.read_csv(records_csv)
        ready = compute_sample_readiness(df)
        status_counts = ready["sample_readiness_status"].value_counts(dropna=False).to_dict()
        st.write(
            {
                "total_rows": int(len(ready)),
                "mean_readiness_score": round(float(ready["sample_readiness_score"].mean()) if len(ready) else 0.0, 4),
                "status_counts": status_counts,
            }
        )
        display_cols = [
            c
            for c in [
                "image_path",
                "sample_readiness_score",
                "sample_readiness_status",
                "caption_quality_score",
                "low_quality_flag",
                "low_quality_reason",
                "recapture_guidance",
                "spectral_consistency_score",
                "spectral_drift_flag",
                "spectral_warning_reason",
            ]
            if c in ready.columns
        ]
        st.dataframe(ready[display_cols], width="stretch")
    except Exception as exc:
        st.error(f"Failed to compute readiness: {exc}")


def render_cell_media_visualization(run_dir: Path) -> None:
    records_csv = run_dir / "records.csv"
    density_dir = run_dir / "artifacts" / "density_maps"
    if not records_csv.exists():
        st.warning(f"records.csv not found in {run_dir}")
        return

    df = pd.read_csv(records_csv)
    if df.empty:
        st.caption("No records available for visualization.")
        return

    st.markdown("#### At-a-glance cell/media metrics")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", int(len(df)))
    confluency_col = "feat_confluency_fraction" if "feat_confluency_fraction" in df.columns else ("confluency_fraction" if "confluency_fraction" in df.columns else None)
    if confluency_col:
        c2.metric("Mean confluency", round(float(df[confluency_col].mean()), 4))
    if "density_mean" in df.columns:
        c3.metric("Mean density", round(float(df["density_mean"].mean()), 4))
    if "media_fraction" in df.columns:
        c4.metric("Mean media fraction", round(float(df["media_fraction"].mean()), 4))

    trend_cols = [c for c in [confluency_col, "density_mean", "media_fraction", "density_std"] if c and c in df.columns]
    if trend_cols:
        st.line_chart(df[trend_cols])

    if not density_dir.exists():
        st.info("Density map artifacts are not present for this run yet.")
        return

    heatmaps = sorted(density_dir.glob("record_*_heatmap.csv"))
    if not heatmaps:
        st.info("No heatmap CSVs found in density artifact folder.")
        return

    options = [p.stem.replace("_heatmap", "") for p in heatmaps]
    selected = st.selectbox("Select record for heatmap/wavetable", options, key="cell_media_record_select")
    heatmap_path = density_dir / f"{selected}_heatmap.csv"
    wavetable_path = density_dir / f"{selected}_wavetable.csv"

    if heatmap_path.exists():
        hdf = pd.read_csv(heatmap_path)
        st.markdown("#### Density heatmap grid")
        numeric_cols = [c for c in hdf.columns if pd.api.types.is_numeric_dtype(hdf[c])]
        if go and len(numeric_cols) > 0 and len(hdf) > 0:
            mat = hdf[numeric_cols].values
            fig = go.Figure(data=go.Heatmap(z=mat, colorscale="Viridis"))
            fig.update_layout(height=400, margin=dict(l=60, r=20, t=20, b=60))
            st.plotly_chart(fig, use_container_width=True, key="cell_media_density_heatmap")
        st.dataframe(hdf, width="stretch", height=min(300, 50 + len(hdf) * 25))

    if wavetable_path.exists():
        wdf = pd.read_csv(wavetable_path)
        wt_cols = [c for c in ["wavetable_x_density", "wavetable_y_density"] if c in wdf.columns]
        if wt_cols:
            st.markdown("#### Density wavetable profiles")
            st.line_chart(wdf[wt_cols])

    render_cell_visualizer_panel(run_dir, df)


def _safe_numeric(series: pd.Series, default: float = 0.0) -> pd.Series:
    vals = pd.to_numeric(series, errors="coerce").fillna(default)
    return vals.astype(float)


def _build_cell_points(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["x", "y", "z", "signal"])
    sample = df.head(max_points).copy()

    x_candidates = ["centroid_x", "center_x", "feat_centroid_x", "x"]
    y_candidates = ["centroid_y", "center_y", "feat_centroid_y", "y"]
    z_candidates = ["centroid_z", "center_z", "feat_centroid_z", "z"]
    signal_candidates = ["density_mean", "feat_confluency_fraction", "caption_quality_score"]

    def pick(candidates: list[str]) -> str | None:
        for c in candidates:
            if c in sample.columns:
                return c
        return None

    x_col = pick(x_candidates)
    y_col = pick(y_candidates)
    z_col = pick(z_candidates)
    s_col = pick(signal_candidates)

    n = len(sample)
    if x_col and y_col:
        x = _safe_numeric(sample[x_col]).reset_index(drop=True)
        y = _safe_numeric(sample[y_col]).reset_index(drop=True)
    else:
        # Fallback synthetic layout if records do not include explicit geometry.
        x = pd.Series([math.cos(i * 0.23) * (1.0 + (i % 7) * 0.04) for i in range(n)])
        y = pd.Series([math.sin(i * 0.23) * (1.0 + (i % 7) * 0.04) for i in range(n)])

    if z_col:
        z = _safe_numeric(sample[z_col]).reset_index(drop=True)
    else:
        z = pd.Series([(i % 25) / 6.0 for i in range(n)])

    if s_col:
        signal = _safe_numeric(sample[s_col]).reset_index(drop=True)
    else:
        signal = pd.Series([float(i % 10) / 10.0 for i in range(n)])

    return pd.DataFrame({"x": x, "y": y, "z": z, "signal": signal})


def _build_cell_figure(
    points: pd.DataFrame,
    title: str,
    eye: dict[str, float],
    projection_type: str,
    show_surface: bool,
    show_points: bool,
    show_hotspots: bool,
    detail_level: int,
    transition_buffer: int,
    show_textbook_structure: bool,
    shading_mode: str,
    show_grid: bool,
    snap_stage: bool,
) -> Any:
    fig = go.Figure()
    t_raw = max(0.0, min(1.0, float(detail_level) / 100.0))
    edge = max(0.0, min(0.45, float(transition_buffer) / 100.0))
    if t_raw <= edge:
        detail_t = 0.0
    elif t_raw >= (1.0 - edge):
        detail_t = 1.0
    else:
        x = (t_raw - edge) / (1.0 - 2.0 * edge)
        detail_t = x * x * (3.0 - 2.0 * x)  # smoothstep
    broad_t = 1.0 - detail_t
    if snap_stage:
        if detail_level < 25:
            detail_t = 0.0
        elif detail_level < 50:
            detail_t = 0.33
        elif detail_level < 75:
            detail_t = 0.66
        else:
            detail_t = 1.0
        broad_t = 1.0 - detail_t

    if shading_mode == "Wireframe":
        mesh_opacity = 0.05 + 0.15 * detail_t
        point_opacity = 0.15 + 0.45 * detail_t
        point_size = 2 + int(2 * detail_t)
    elif shading_mode == "Solid":
        mesh_opacity = 0.14 + 0.35 * detail_t
        point_opacity = 0.20 + 0.60 * detail_t
        point_size = 2 + int(3 * detail_t)
    else:  # Material-like
        mesh_opacity = 0.18 + 0.42 * detail_t
        point_opacity = 0.25 + 0.70 * detail_t
        point_size = 2 + int(4 * detail_t)

    if show_textbook_structure and broad_t > 0.01 and len(points) > 0:
        cx = float(points["x"].mean())
        cy = float(points["y"].mean())
        cz = float(points["z"].mean())
        rx = max(float(points["x"].std()) * 2.4, 0.5)
        ry = max(float(points["y"].std()) * 2.4, 0.5)
        rz = max(float(points["z"].std()) * 2.4, 0.5)

        def _ring(axis: str, n: int = 72) -> tuple[list[float], list[float], list[float]]:
            xs: list[float] = []
            ys: list[float] = []
            zs: list[float] = []
            for i in range(n):
                a = (2.0 * math.pi * i) / (n - 1)
                if axis == "xy":
                    xs.append(cx + rx * math.cos(a))
                    ys.append(cy + ry * math.sin(a))
                    zs.append(cz)
                elif axis == "xz":
                    xs.append(cx + rx * math.cos(a))
                    ys.append(cy)
                    zs.append(cz + rz * math.sin(a))
                else:  # yz
                    xs.append(cx)
                    ys.append(cy + ry * math.cos(a))
                    zs.append(cz + rz * math.sin(a))
            return xs, ys, zs

        for axis in ["xy", "xz", "yz"]:
            xs, ys, zs = _ring(axis)
            fig.add_trace(
                go.Scatter3d(
                    x=xs,
                    y=ys,
                    z=zs,
                    mode="lines",
                    line={"width": 4, "color": f"rgba(50,120,220,{0.35 * broad_t + 0.15})"},
                    name="Textbook structure",
                    showlegend=False,
                )
            )

        fig.add_trace(
            go.Scatter3d(
                x=[cx],
                y=[cy],
                z=[cz],
                mode="markers",
                marker={"size": 7, "color": f"rgba(50,120,220,{0.55 * broad_t + 0.2})"},
                name="Structure center",
                showlegend=False,
            )
        )

    if show_surface and len(points) >= 20:
        fig.add_trace(
            go.Mesh3d(
                x=points["x"],
                y=points["y"],
                z=points["z"],
                intensity=points["signal"],
                colorscale="Viridis",
                opacity=mesh_opacity,
                alphahull=4,
                name="Reconstructed surface",
                showscale=False,
            )
        )

    if show_points:
        fig.add_trace(
            go.Scatter3d(
                x=points["x"],
                y=points["y"],
                z=points["z"],
                mode="markers",
                marker={
                    "size": point_size,
                    "color": points["signal"],
                    "colorscale": "Turbo",
                    "opacity": point_opacity,
                },
                name="Cell points",
                showlegend=False,
            )
        )

    if show_hotspots and len(points) > 0:
        threshold = float(points["signal"].quantile(0.85))
        hot = points[points["signal"] >= threshold]
        if not hot.empty:
            fig.add_trace(
                go.Scatter3d(
                    x=hot["x"],
                    y=hot["y"],
                    z=hot["z"],
                    mode="markers",
                    marker={"size": 5 + int(2 * detail_t), "color": "#ff3b30", "opacity": 0.35 + 0.6 * detail_t},
                    name="High-signal hotspots",
                    showlegend=False,
                )
            )

    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 30, "b": 0},
        title=title,
        scene={
            "camera": {"eye": eye, "projection": {"type": projection_type}},
            "xaxis": {"title": "X", "showgrid": show_grid, "zeroline": show_grid},
            "yaxis": {"title": "Y", "showgrid": show_grid, "zeroline": show_grid},
            "zaxis": {"title": "Z", "showgrid": show_grid, "zeroline": show_grid},
            "aspectmode": "data",
        },
    )
    return fig


def _detail_stage(detail_level: int) -> tuple[str, str]:
    if detail_level < 25:
        return (
            "Structure",
            "Textbook-style whole structure view. Best for orientation and broad context.",
        )
    if detail_level < 50:
        return (
            "Region",
            "Regional anatomy view. You can inspect broad sub-areas before drilling down.",
        )
    if detail_level < 75:
        return (
            "Cluster",
            "Cell-cluster view. Useful for spotting pockets and local variation.",
        )
    return (
        "Cell",
        "Cell-level detail view. Best for point-level inspection and hotspot review.",
    )


def _coarse_points(points: pd.DataFrame, bins_per_axis: int) -> pd.DataFrame:
    if points.empty:
        return points
    if bins_per_axis < 2:
        return points.copy()
    work = points.copy()
    for axis in ["x", "y", "z"]:
        lo = float(work[axis].min())
        hi = float(work[axis].max())
        if hi <= lo:
            work[f"{axis}_bin"] = 0
        else:
            scaled = (work[axis] - lo) / (hi - lo)
            work[f"{axis}_bin"] = (scaled * (bins_per_axis - 1)).round().astype(int)
    grouped = (
        work.groupby(["x_bin", "y_bin", "z_bin"], as_index=False)
        .agg({"x": "mean", "y": "mean", "z": "mean", "signal": "mean"})
        .reset_index(drop=True)
    )
    return grouped[["x", "y", "z", "signal"]]


def _projection_heatmap(points: pd.DataFrame, axis_a: str, axis_b: str, bins: int = 24) -> tuple[pd.DataFrame, list[float], list[float]]:
    if points.empty:
        return pd.DataFrame(), [], []
    a = points[axis_a]
    b = points[axis_b]
    a_edges = pd.interval_range(start=float(a.min()), end=float(a.max()) + 1e-9, periods=bins)
    b_edges = pd.interval_range(start=float(b.min()), end=float(b.max()) + 1e-9, periods=bins)
    work = points.copy()
    work["a_bin"] = pd.cut(a, bins=[x.left for x in a_edges] + [a_edges[-1].right], include_lowest=True)
    work["b_bin"] = pd.cut(b, bins=[x.left for x in b_edges] + [b_edges[-1].right], include_lowest=True)
    mat = work.pivot_table(index="b_bin", columns="a_bin", values="signal", aggfunc="mean", fill_value=0.0)
    mat = mat.sort_index(ascending=True)
    mat = mat.reindex(sorted(mat.columns), axis=1)
    a_centers = [float(iv.mid) for iv in mat.columns]
    b_centers = [float(iv.mid) for iv in mat.index]
    return mat, a_centers, b_centers


def render_cell_visualizer_panel(run_dir: Path, df: pd.DataFrame) -> None:
    st.markdown("#### 3D Cell Visualizer (Prototype)")
    st.caption(
        "Blender-style panel with one perspective view and three orthographic portholes (top, front, side)."
    )

    if go is None:
        st.info("Plotly is not available in this Python environment yet, so the 3D panel cannot be rendered.")
        return

    c1, c2 = st.columns(2)
    with c1:
        max_points = st.slider(
            "Point sample size",
            min_value=80,
            max_value=1500,
            value=400,
            step=20,
            help=mode_aware_tooltip(
                "How many points to show in 3D. Lower is faster. Higher shows more detail.",
                "Maximum sampled points used to render mesh/point overlays.",
                current_power_user_mode(),
            ),
        )
        detail_level = st.slider(
            "Detail level",
            min_value=0,
            max_value=100,
            value=70,
            step=1,
            help=mode_aware_tooltip(
                "Slide left for broad textbook-style structure. Slide right for detailed cell-level view.",
                "Controls blend from macro structural abstraction (0) to cell-level detail (100).",
                current_power_user_mode(),
            ),
        )
        snap_stage = st.toggle(
            "Snap detail to stages",
            value=False,
            help=mode_aware_tooltip(
                "When on, the slider snaps to Structure, Region, Cluster, and Cell levels.",
                "Quantize detail slider into discrete hierarchy stages.",
                current_power_user_mode(),
            ),
        )
    with c2:
        st.caption("Viewport + Overlays")
        shading_mode = st.selectbox(
            "Viewport shading",
            ["Material-like", "Solid", "Wireframe"],
            index=0,
            help=mode_aware_tooltip(
                "Choose the look of the 3D view, similar to Blender viewport styles.",
                "Viewport appearance preset analogous to Blender shading modes.",
                current_power_user_mode(),
            ),
        )
        show_grid = st.checkbox(
            "Show floor/grid",
            value=True,
            help=mode_aware_tooltip(
                "Shows guide lines to help with orientation, like a floor grid.",
                "Display axis grids/zero-lines for spatial orientation.",
                current_power_user_mode(),
            ),
        )
        transition_buffer = st.slider(
            "Transition buffer",
            min_value=0,
            max_value=30,
            value=12,
            step=1,
            help=mode_aware_tooltip(
                "Makes transitions smoother between broad and detailed views.",
                "Blend smoothing window for detail interpolation (smoothstep edge width).",
                current_power_user_mode(),
            ),
        )
        show_textbook_structure = st.checkbox(
            "Show broad textbook structure",
            value=True,
            help=mode_aware_tooltip(
                "Adds a simple structure guide when you are zoomed to broader detail levels.",
                "Render macro structural guide overlays (orthogonal ellipsoid rings).",
                current_power_user_mode(),
            ),
        )
        show_surface = st.checkbox(
            "Show reconstructed surface",
            value=True,
            help=mode_aware_tooltip(
                "Adds a transparent surface around the point cloud so shape is easier to read.",
                "Display alpha-hull mesh reconstruction around sampled points.",
                current_power_user_mode(),
            ),
        )
        show_points = st.checkbox(
            "Show cell points",
            value=True,
            help=mode_aware_tooltip(
                "Shows each sampled data point in 3D.",
                "Render sampled point-cloud markers.",
                current_power_user_mode(),
            ),
        )
        show_hotspots = st.checkbox(
            "Highlight high-signal hotspots",
            value=True,
            help=mode_aware_tooltip(
                "Marks the strongest signal areas in red to guide inspection.",
                "Highlight top-quantile signal points as hotspot overlay.",
                current_power_user_mode(),
            ),
        )

    points = _build_cell_points(df, max_points=max_points)
    if points.empty:
        st.info("No points available for 3D rendering.")
        return
    stage_name, stage_desc = _detail_stage(detail_level)
    st.caption(f"Detail stage: **{stage_name}**")
    st.caption(stage_desc)

    # Build a stage-aware point set so the slider behaves like meaningful hierarchy levels.
    if detail_level < 25:
        view_points = _coarse_points(points, bins_per_axis=4)
    elif detail_level < 50:
        view_points = _coarse_points(points, bins_per_axis=7)
    elif detail_level < 75:
        view_points = _coarse_points(points, bins_per_axis=10)
    else:
        view_points = points
    if view_points.empty:
        view_points = points

    base = f"cellviz_{run_dir.name}"
    p_col, t_col = st.columns(2)
    f_col, s_col = st.columns(2)

    with p_col:
        fig_p = _build_cell_figure(
            points=view_points,
            title="Perspective",
            eye={"x": 1.8, "y": 1.6, "z": 1.2},
            projection_type="perspective",
            show_surface=show_surface,
            show_points=show_points,
            show_hotspots=show_hotspots,
            detail_level=detail_level,
            transition_buffer=transition_buffer,
            show_textbook_structure=show_textbook_structure,
            shading_mode=shading_mode,
            show_grid=show_grid,
            snap_stage=snap_stage,
        )
        st.plotly_chart(fig_p, use_container_width=True, key=f"{base}_persp")

    with t_col:
        fig_top = _build_cell_figure(
            points=view_points,
            title="Top (Ortho)",
            eye={"x": 0.0, "y": 0.0, "z": 2.8},
            projection_type="orthographic",
            show_surface=show_surface,
            show_points=show_points,
            show_hotspots=show_hotspots,
            detail_level=detail_level,
            transition_buffer=transition_buffer,
            show_textbook_structure=show_textbook_structure,
            shading_mode=shading_mode,
            show_grid=show_grid,
            snap_stage=snap_stage,
        )
        st.plotly_chart(fig_top, use_container_width=True, key=f"{base}_top")

    with f_col:
        fig_front = _build_cell_figure(
            points=view_points,
            title="Front (Ortho)",
            eye={"x": 0.0, "y": 2.8, "z": 0.0},
            projection_type="orthographic",
            show_surface=show_surface,
            show_points=show_points,
            show_hotspots=show_hotspots,
            detail_level=detail_level,
            transition_buffer=transition_buffer,
            show_textbook_structure=show_textbook_structure,
            shading_mode=shading_mode,
            show_grid=show_grid,
            snap_stage=snap_stage,
        )
        st.plotly_chart(fig_front, use_container_width=True, key=f"{base}_front")

    with s_col:
        fig_side = _build_cell_figure(
            points=view_points,
            title="Side (Ortho)",
            eye={"x": 2.8, "y": 0.0, "z": 0.0},
            projection_type="orthographic",
            show_surface=show_surface,
            show_points=show_points,
            show_hotspots=show_hotspots,
            detail_level=detail_level,
            transition_buffer=transition_buffer,
            show_textbook_structure=show_textbook_structure,
            shading_mode=shading_mode,
            show_grid=show_grid,
            snap_stage=snap_stage,
        )
        st.plotly_chart(fig_side, use_container_width=True, key=f"{base}_side")

    st.markdown("#### Integrated Visual Analysis")
    st.caption(
        "Linked projections for quick inspection: XY, XZ, YZ density maps and signal distribution."
    )
    h1, h2 = st.columns(2)
    h3, h4 = st.columns(2)

    xy_mat, xy_x, xy_y = _projection_heatmap(view_points, "x", "y", bins=22)
    xz_mat, xz_x, xz_y = _projection_heatmap(view_points, "x", "z", bins=22)
    yz_mat, yz_x, yz_y = _projection_heatmap(view_points, "y", "z", bins=22)

    with h1:
        if not xy_mat.empty:
            fig_xy = go.Figure(
                data=go.Heatmap(
                    z=xy_mat.values,
                    x=xy_x,
                    y=xy_y,
                    colorscale="Viridis",
                    colorbar={"title": "Signal"},
                )
            )
            fig_xy.update_layout(margin={"l": 0, "r": 0, "t": 30, "b": 0}, title="XY Projection")
            st.plotly_chart(fig_xy, use_container_width=True, key=f"{base}_xy")
    with h2:
        if not xz_mat.empty:
            fig_xz = go.Figure(
                data=go.Heatmap(
                    z=xz_mat.values,
                    x=xz_x,
                    y=xz_y,
                    colorscale="Cividis",
                    colorbar={"title": "Signal"},
                )
            )
            fig_xz.update_layout(margin={"l": 0, "r": 0, "t": 30, "b": 0}, title="XZ Projection")
            st.plotly_chart(fig_xz, use_container_width=True, key=f"{base}_xz")
    with h3:
        if not yz_mat.empty:
            fig_yz = go.Figure(
                data=go.Heatmap(
                    z=yz_mat.values,
                    x=yz_x,
                    y=yz_y,
                    colorscale="Magma",
                    colorbar={"title": "Signal"},
                )
            )
            fig_yz.update_layout(margin={"l": 0, "r": 0, "t": 30, "b": 0}, title="YZ Projection")
            st.plotly_chart(fig_yz, use_container_width=True, key=f"{base}_yz")
    with h4:
        fig_hist = go.Figure(
            data=go.Histogram(x=view_points["signal"], nbinsx=20, marker={"color": "#3d6fb6"})
        )
        fig_hist.update_layout(
            margin={"l": 0, "r": 0, "t": 30, "b": 0},
            title="Signal Distribution",
            xaxis_title="Signal value",
            yaxis_title="Count",
        )
        st.plotly_chart(fig_hist, use_container_width=True, key=f"{base}_hist")


def default_python_exe() -> str:
    candidates = [
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv" / "bin" / "python",
        PROJECT_ROOT / ".venv311" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv311" / "bin" / "python",
        PROJECT_ROOT / ".venv_caption" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv_caption" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def default_rscript_exe() -> str:
    candidates = [
        Path("C:/Program Files/R/R-4.4.0/bin/Rscript.exe"),
        Path("C:/Program Files/R/R-4.3.3/bin/Rscript.exe"),
        Path("C:/Program Files/R/R-4.3.2/bin/Rscript.exe"),
        Path("C:/Program Files/R/R-4.3.1/bin/Rscript.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "Rscript"


def detect_host_platform() -> dict[str, str]:
    system_name = platform.system().strip().lower()
    if system_name == "windows":
        platform_id = "windows"
        label = "Windows"
    elif system_name == "darwin":
        platform_id = "macos"
        label = "macOS"
    elif system_name == "linux":
        platform_id = "linux"
        label = "Linux"
    else:
        platform_id = "other"
        label = platform.system() or "Unknown"
    return {"id": platform_id, "label": label}


def _platform_source_candidates(platform_id: str, root: Path) -> list[Path]:
    home = Path.home()
    if platform_id == "windows":
        return [
            Path("C:/LabData/InstrumentExports"),
            Path("D:/LabData/InstrumentExports"),
            home / "Documents" / "LabInstruments",
            home / "Desktop" / "LabInstruments",
            root / "instrument_ingest" / "dropbox",
        ]
    if platform_id == "macos":
        return [
            home / "Documents" / "LabInstruments",
            home / "Desktop" / "LabInstruments",
            Path("/Volumes/LabShare/InstrumentExports"),
            root / "instrument_ingest" / "dropbox",
        ]
    if platform_id == "linux":
        return [
            home / "lab_instruments",
            home / "Documents" / "LabInstruments",
            Path("/mnt/labshare/instrument_exports"),
            Path("/data/lab/instrument_exports"),
            root / "instrument_ingest" / "dropbox",
        ]
    return [root / "instrument_ingest" / "dropbox"]


def auto_configure_lab_implements(config_path: Path, platform_id: str, root: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    bridge_cfg = cfg.setdefault("instrument_bridge", {})
    workspace_cfg = cfg.setdefault("google_workspace", {})

    bridge_cfg["enabled"] = True
    bridge_cfg["recursive"] = bool(bridge_cfg.get("recursive", True))
    bridge_cfg["poll_seconds"] = int(bridge_cfg.get("poll_seconds", 30))
    bridge_cfg["min_new_images"] = int(bridge_cfg.get("min_new_images", 1))
    bridge_cfg["state_file"] = str(root / ".instrument_bridge_state.json")
    bridge_cfg["staging_root"] = str(root / "instrument_ingest")

    candidate_paths = _platform_source_candidates(platform_id, root)
    found_sources = [str(p) for p in candidate_paths if p.exists() and p.is_dir()]

    fallback_dropbox = root / "instrument_ingest" / "dropbox"
    fallback_dropbox.mkdir(parents=True, exist_ok=True)

    existing_sources = bridge_cfg.get("sources", [])
    existing_sources = existing_sources if isinstance(existing_sources, list) else []
    normalized_existing = [str(Path(str(p)).expanduser()) for p in existing_sources if str(p).strip()]

    merged = list(dict.fromkeys(normalized_existing + found_sources))
    if str(fallback_dropbox) not in merged:
        merged.append(str(fallback_dropbox))
    bridge_cfg["sources"] = merged

    workspace_cfg["drive_mirror_dir"] = str(root / "google_drive_ingest")
    workspace_cfg["credentials_file"] = str(Path.home() / "Documents" / "credentials.json")
    workspace_cfg.setdefault("token_file", str(Path.home() / "Documents" / "token_barlowa124_full3.json"))
    workspace_cfg.setdefault("oauth_host", "127.0.0.1")
    workspace_cfg.setdefault("oauth_port", 8765)

    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return {
        "config": str(config_path),
        "sources": bridge_cfg["sources"],
        "fallback_dropbox": str(fallback_dropbox),
        "platform": platform_id,
    }


def python_runtime_summary(python_exe: str) -> dict[str, str]:
    path = Path(python_exe)
    if not path.exists():
        return {
            "value": "Missing",
            "delta": "Check Python path",
            "detail": python_exe,
        }

    version_text = "Unknown"
    try:
        result = run_command([python_exe, "--version"])
        raw = (result.get("stdout") or result.get("stderr") or "").strip()
        if raw:
            parts = raw.replace("Python", "").strip().split()
            version_text = parts[0] if parts else raw
    except Exception:
        version_text = "Unknown"

    return {
        "value": version_text,
        "delta": path.name,
        "detail": str(path),
    }


def latest_run_summary(run_dir: Path | None) -> dict[str, str]:
    if not run_dir:
        return {
            "value": "None",
            "delta": "Run Daily QC to create output",
            "detail": "No output_* run folder detected yet.",
            "diagnosis": "No run artifacts found yet.",
            "severity": "info",
            "snapshot": "No QC snapshot available.",
        }

    status_path = run_dir / "run_status.json"
    metadata_path = run_dir / "run_metadata.json"
    status_light = "Unknown"
    image_count = 0
    failed_count = 0
    low_quality_rate = 0.0
    spectral_drift_rate = 0.0
    median_caption_quality = 0.0
    captioning_enabled = None

    if status_path.exists():
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            status_light = str(payload.get("run_status_light", "Unknown"))
            image_count = int(payload.get("image_count", 0))
            failed_count = int(payload.get("failed_count", 0))
            low_quality_rate = float(payload.get("low_quality_rate", 0.0))
            spectral_drift_rate = float(payload.get("spectral_drift_rate", 0.0))
            median_caption_quality = float(payload.get("median_caption_quality", 0.0))
        except Exception:
            pass

    if metadata_path.exists():
        try:
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            captioning_enabled = meta.get("captioning_enabled")
        except Exception:
            pass

    diagnosis_parts = []
    if failed_count > 0:
        diagnosis_parts.append(f"{failed_count} failed items")
    if low_quality_rate > 0:
        diagnosis_parts.append(f"low-quality rate {low_quality_rate:.1%}")
    if spectral_drift_rate > 0:
        diagnosis_parts.append(f"spectral drift rate {spectral_drift_rate:.1%}")
    if captioning_enabled is False:
        diagnosis_parts.append("captioning disabled")

    status_norm = status_light.strip().lower()
    if status_norm == "green":
        severity = "success"
        diagnosis = "Handoff-ready: quality and drift checks are within thresholds."
    elif status_norm == "yellow":
        severity = "warning"
        diagnosis = "Review before export: flagged quality/drift signals need operator confirmation."
    elif status_norm == "red":
        severity = "error"
        diagnosis = "Recapture required: run is not handoff-ready; investigate quality/failure causes."
    else:
        severity = "info"
        diagnosis = "Status check needed: run signals are present but not fully classified."

    if diagnosis_parts:
        diagnosis = f"{diagnosis} Signals: {', '.join(diagnosis_parts)}."

    updated = datetime.fromtimestamp(run_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    captioning_text = "on" if captioning_enabled is True else "off" if captioning_enabled is False else "unknown"
    snapshot = (
        f"LQ {low_quality_rate:.1%} • median caption {median_caption_quality:.3f} • "
        f"drift {spectral_drift_rate:.1%} • captioning {captioning_text} • {updated}"
    )
    return {
        "value": status_light,
        "delta": f"{image_count} imgs, {failed_count} failed",
        "detail": f"{run_dir.name} • updated {updated}",
        "diagnosis": diagnosis,
        "severity": severity,
        "snapshot": snapshot,
    }


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return cleaned or "untitled"


def save_bug_report(
    report_dir: Path,
    title: str,
    area: str,
    severity: str,
    reproducible: bool,
    expected: str,
    actual: str,
    steps: str,
    data_paths: str,
    notes: str,
    python_exe: str,
    project_root: Path,
    interface_mode: str,
    latest_run_name: str,
) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{stamp}_{slugify(title)}"

    payload = {
        "schema_version": "1.0",
        "timestamp_local": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "area": area,
        "severity": severity,
        "reproducible": reproducible,
        "expected": expected,
        "actual": actual,
        "steps_to_reproduce": [line.strip() for line in (steps or "").splitlines() if line.strip()],
        "data_paths": [line.strip() for line in (data_paths or "").splitlines() if line.strip()],
        "notes": notes,
        "environment": {
            "python_executable": python_exe,
            "project_root": str(project_root),
            "interface_mode": interface_mode,
            "latest_run": latest_run_name,
        },
        "labels": ["lab-webui", "bug-report", "ai-crawlable", f"severity:{severity.lower()}", f"area:{slugify(area)}"],
    }

    json_path = report_dir / f"{base_name}.json"
    md_path = report_dir / f"{base_name}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md = f"""# Lab Bug Report: {title}

## Metadata
- Timestamp: {payload['timestamp_local']}
- Area: {area}
- Severity: {severity}
- Reproducible: {reproducible}
- Interface mode: {interface_mode}
- Latest run: {latest_run_name}

## Expected Behavior
{expected}

## Actual Behavior
{actual}

## Steps to Reproduce
{steps}

## Data and File Paths
{data_paths}

## Additional Notes
{notes}

## Machine-Readable Companion
- JSON: {json_path.name}
"""
    md_path.write_text(md, encoding="utf-8")
    return md_path, json_path


def render_glutamate_reminder() -> None:
    st.warning(
        "Lab Reminder: Use glutamate protocol controls/checks before final interpretation and handoff."
    )


def render_data_preservation_reminder() -> None:
    st.info(
        "Data Reminder: Save all outputs and notes. All data is useful for QA, trend analysis, reproducibility, and future model improvement."
    )


def render_streamlined_signpost(latest_run: Path | None) -> None:
    step1_state = "✅ Completed" if latest_run else "▶ Start here"
    step2_state = "✅ Available" if latest_run else "⏳ After Step 1"
    step3_state = "✅ Available" if latest_run else "⏳ After Step 2"

    with st.container(border=True):
        st.markdown("##### Quick Visual Guide")
        st.caption("Follow left to right. Each step shows what to provide and what output to expect.")
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**1) Daily QC**  \\n+{step1_state}")
        c2.markdown(f"**2) Readiness Gate**  \\n+{step2_state}")
        c3.markdown(f"**3) ELN/LIMS Export**  \\n+{step3_state}")
        if latest_run:
            st.success("Recommended next click: **Compute Readiness** (Step 2), then **Export Package** (Step 3).")
        else:
            st.success("Recommended next click: **Start Daily QC** (Step 1).")


def render_start_here_navigator() -> str:
    current_focus = st.session_state.get("guided_focus_step", "1")
    with st.container(border=True):
        st.markdown("##### Start Here Navigator")
        st.caption("Use this quick navigator to focus on one step at a time.")
        c1, c2, c3 = st.columns(3)
        if c1.button(
            "Focus Step 1",
            key="focus_step_1",
            help=mode_aware_tooltip(
                "Jump your attention to Step 1 so you can start the quality check first.",
                "Highlights Daily QC for run generation from microscopy inputs.",
                current_power_user_mode(),
            ),
            width="stretch",
        ):
            st.session_state["guided_focus_step"] = "1"
            current_focus = "1"
        if c2.button(
            "Focus Step 2",
            key="focus_step_2",
            help=mode_aware_tooltip(
                "Jump to Step 2 to review results and sort items into ready, review, or hold.",
                "Highlights Readiness after Daily QC for ready/review/hold triage.",
                current_power_user_mode(),
            ),
            width="stretch",
        ):
            st.session_state["guided_focus_step"] = "2"
            current_focus = "2"
        if c3.button(
            "Focus Step 3",
            key="focus_step_3",
            help=mode_aware_tooltip(
                "Jump to Step 3 to create the package you share at handoff.",
                "Highlights ELN/LIMS Export to package handoff-ready outputs.",
                current_power_user_mode(),
            ),
            width="stretch",
        ):
            st.session_state["guided_focus_step"] = "3"
            current_focus = "3"
        st.info(f"Current focus: Step {current_focus}")
    return current_focus


def render_step_cues(input_text: str, action_text: str, output_text: str) -> None:
    st.caption(f"Input: {input_text}")
    st.caption(f"Action: {action_text}")
    st.caption(f"Output: {output_text}")


def run_output_dirs(root: Path) -> list[Path]:
    dirs = [p for p in root.glob("output_*") if p.is_dir()]
    return sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)


def default_cellmedia_run_dir(root: Path) -> Path | None:
    preferred = root / PREFERRED_CELLMEDIA_RUN
    if preferred.exists() and preferred.is_dir() and (preferred / "records.csv").exists():
        return preferred
    return latest_run_dir(root)


def hash_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def create_run_fingerprint(run_dir: Path, config_path: Path, python_exe: str, project_root: Path) -> Path:
    git_commit = "unknown"
    git_dirty = "unknown"
    try:
        head = subprocess.run(["git", "-C", str(project_root), "rev-parse", "HEAD"], capture_output=True, text=True)
        status = subprocess.run(["git", "-C", str(project_root), "status", "--porcelain"], capture_output=True, text=True)
        if head.returncode == 0:
            git_commit = head.stdout.strip()
        if status.returncode == 0:
            git_dirty = "yes" if status.stdout.strip() else "no"
    except Exception:
        pass

    tracked_files = [
        run_dir / "records.csv",
        run_dir / "records.jsonl",
        run_dir / "run_metadata.json",
        run_dir / "run_status.json",
        run_dir / "failed_records.json",
        run_dir / "analyzer_telemetry_summary.json",
    ]
    file_hashes = {f.name: hash_file(f) for f in tracked_files if f.exists()}

    payload = {
        "schema_version": "1.0",
        "generated_at_local": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "config_path": str(config_path),
        "python_executable": python_exe,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "file_hashes": file_hashes,
        "note": "Run fingerprint supports auditability and exact run reconstruction.",
    }
    out = run_dir / "run_fingerprint.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def replay_failed_run(root: Path, python_exe: str, config_path: Path) -> dict[str, Any]:
    return run_command([python_exe, str(root / "run_pipeline.py"), "--config", str(config_path)], cwd=root)


def run_metaflux_from_webapp(root: Path, rscript_exe: str, config_path: Path) -> dict[str, Any]:
    script_path = root / "run_metaflux_analyzer.R"
    if not script_path.exists():
        return {"ok": False, "returncode": 127, "stdout": "", "stderr": f"METAFlux launcher not found: {script_path}"}
    if not config_path.exists():
        return {"ok": False, "returncode": 2, "stdout": "", "stderr": f"METAFlux config not found: {config_path}"}
    return run_command([rscript_exe, str(script_path), "--config", str(config_path)], cwd=root)


def _prepare_metaflux_refactored(
    root: Path, rscript_exe: str, config_path: Path, rnaseq_override: Path | None = None
) -> tuple[list[str], Path, Path] | None:
    """Prepare METAFlux refactored run. Returns (cmd, cwd, out_dir) or None on error."""
    script_path = root / "metaflux_pipeline_refactored.R"
    if not script_path.exists():
        return None
    if not config_path.exists():
        return None
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    proj = Path(cfg.get("paths", {}).get("project_root", str(Path.home() / "Documents")))
    out_dir = proj / "runs" / f"webui_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg.copy()
    cfg.setdefault("paths", {})
    cfg.setdefault("output", {})["output_dir"] = str(out_dir)
    if rnaseq_override:
        cfg["paths"]["rnaseq_file"] = str(rnaseq_override)
    runtime_cfg = root / "_tmp_metaflux_runtime_config.yaml"
    runtime_cfg.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    cmd = [rscript_exe, str(script_path), str(runtime_cfg)]
    return (cmd, root, out_dir)


def run_metaflux_refactored(root: Path, rscript_exe: str, config_path: Path, rnaseq_override: Path | None = None) -> tuple[dict[str, Any], Path | None]:
    """Run metaflux_pipeline_refactored.R with YAML config. Returns (result, output_dir or None)."""
    prep = _prepare_metaflux_refactored(root, rscript_exe, config_path, rnaseq_override)
    if not prep:
        script_path = root / "metaflux_pipeline_refactored.R"
        if not script_path.exists():
            return ({"ok": False, "returncode": 127, "stdout": "", "stderr": f"Pipeline not found: {script_path}"}, None)
        return ({"ok": False, "returncode": 2, "stdout": "", "stderr": f"Config not found: {config_path}"}, None)
    cmd, cwd, out_dir = prep
    result = run_command(cmd, cwd=cwd)
    return (result, out_dir if result.get("ok") else None)


def _zip_dir(out_dir: Path) -> Any:
    try:
        import io as _io
        import zipfile as _zipfile
        buf = _io.BytesIO()
        with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
            for p in out_dir.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(out_dir))
        buf.seek(0)
        return buf
    except Exception:
        return None


def render_metaflux_results(out_dir: Path) -> None:
    """Display METAFlux pipeline outputs: heatmap, boxplot, CSVs, metadata, report bundle."""
    heatmap = out_dir / "pathway_heatmap.png"
    boxplot = out_dir / "nutrient_flux_boxplot.png"
    if heatmap.exists():
        st.image(str(heatmap), caption="Pathway heatmap", use_container_width=True)
    if boxplot.exists():
        st.image(str(boxplot), caption="Nutrient flux boxplot", use_container_width=True)
    csvs = [p for p in out_dir.glob("*.csv")]
    if csvs:
        st.subheader("CSV outputs")
        for p in sorted(csvs):
            with st.expander(p.name):
                try:
                    df = pd.read_csv(p)
                    st.dataframe(df, use_container_width=True, height=min(300, 50 + len(df) * 25))
                    st.download_button(f"Download {p.name}", p.read_bytes(), p.name, key=f"metaflux_dl_{p.name}")
                except Exception as e:
                    st.text(str(e))
    meta = out_dir / "run_metadata.json"
    if meta.exists():
        with st.expander("Run metadata"):
            st.json(json.loads(meta.read_text(encoding="utf-8")))
    buf = _zip_dir(out_dir)
    if buf:
        st.download_button("Download full report bundle (ZIP)", buf.getvalue(), f"metaflux_report_{out_dir.name}.zip", key=f"metaflux_bundle_{out_dir.name}")


def write_runtime_config(base_config_path: Path, runtime_overrides: dict[str, Any], out_path: Path) -> Path:
    base = yaml.safe_load(base_config_path.read_text(encoding="utf-8"))
    for key, value in runtime_overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key].update(value)
        else:
            base[key] = value
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")
    return out_path


def collect_run_trends(root: Path, day_window: int = 30) -> pd.DataFrame:
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=day_window)
    rows: list[dict[str, Any]] = []

    for run_dir in run_output_dirs(root):
        meta_path = run_dir / "run_metadata.json"
        records_path = run_dir / "records.csv"
        status_path = run_dir / "run_status.json"
        if not meta_path.exists() or not records_path.exists():
            continue

        ts = pd.Timestamp.fromtimestamp(run_dir.stat().st_mtime)
        if ts < cutoff:
            continue

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
            df = pd.read_csv(records_path)
        except Exception:
            continue

        hold_count = int((df.get("sample_readiness_status") == "hold").sum()) if "sample_readiness_status" in df.columns else 0
        rows.append(
            {
                "timestamp": ts,
                "run_name": run_dir.name,
                "processed_count": int(meta.get("processed_count", len(df))),
                "failed_count": int(meta.get("failed_count", 0)),
                "low_quality_rate": float(status.get("low_quality_rate", 0.0)),
                "median_caption_quality": float(status.get("median_caption_quality", 0.0)),
                "hold_count": hold_count,
                "spectral_drift_rate": float(status.get("spectral_drift_rate", 0.0)),
            }
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("timestamp")


def compute_lab_alerts(root: Path, max_low_quality_rate: float = 0.25) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    latest = latest_run_dir(root)
    if not latest:
        return alerts

    status_path = latest / "run_status.json"
    records_path = latest / "records.csv"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if int(status.get("failed_count", 0)) > 0:
                alerts.append({"severity": "high", "message": f"Latest run has failed records: {status.get('failed_count')}"})
            if float(status.get("low_quality_rate", 0.0)) > max_low_quality_rate:
                alerts.append({"severity": "medium", "message": f"Low-quality rate is high: {status.get('low_quality_rate')}"})
            if float(status.get("spectral_drift_rate", 0.0)) > 0.20:
                alerts.append({"severity": "medium", "message": f"Spectral drift rate is high: {status.get('spectral_drift_rate')}"})
        except Exception:
            pass

    if records_path.exists():
        try:
            df = pd.read_csv(records_path)
            if "sample_readiness_status" in df.columns:
                hold_count = int((df["sample_readiness_status"] == "hold").sum())
                if hold_count > 0:
                    alerts.append({"severity": "high", "message": f"Readiness has hold samples: {hold_count}"})
        except Exception:
            pass

    promo_path = root / "model_promotion_decision.json"
    if promo_path.exists():
        try:
            decision = json.loads(promo_path.read_text(encoding="utf-8"))
            if not bool(decision.get("promote", True)):
                alerts.append({"severity": "medium", "message": "Latest model promotion decision is DO NOT PROMOTE."})
        except Exception:
            pass

    return alerts


def render_qc_checklist_gate(key_prefix: str) -> bool:
    st.markdown("##### Pre-Export QC Checklist")
    c1 = st.checkbox("Glutamate controls/checks completed", key=f"{key_prefix}_glutamate")
    c2 = st.checkbox("All generated data has been saved", key=f"{key_prefix}_savedata")
    c3 = st.checkbox("Anomalies and recapture notes have been documented", key=f"{key_prefix}_notes")
    c4 = st.checkbox("Calibration evidence/profile documented for this run", key=f"{key_prefix}_calibration")
    ready = bool(c1 and c2 and c3 and c4)
    if not ready:
        st.caption("Complete checklist items to unlock export.")
    return ready


def render_collaboration_panel(
    root: Path,
    current_user: str,
    api_base_url: str,
    use_local_api: bool,
    default_area: str = "lab-ops",
) -> None:
    if not HAS_LAB_COLLAB:
        st.info("Collaboration tab requires the `lab_collab` module. Install it or run with collaboration disabled.")
        return
    db_path = default_db_path(root)
    init_collab_db(db_path)

    with st.container(border=True):
        st.markdown("### Collaboration Hub")
        st.caption(
            "Google Docs-style collaboration for lab workflow: track views/edits, comments, and proposed edits."
        )
        st.caption(f"Shared DB: {db_path}")
        st.caption(
            f"Mode: {'Local API' if use_local_api else 'Direct DB fallback'}"
            + (f" ({api_base_url})" if use_local_api else "")
        )

        c1, c2, c3 = st.columns(3)
        area = c1.text_input("Area", value=default_area, key="collab_area")
        log_context = c2.text_input(
            "View context",
            value="Opened dashboard",
            key="collab_view_context",
        )
        edit_summary = c3.text_input(
            "Edit summary",
            value="Adjusted workflow parameters",
            key="collab_edit_summary",
        )

        b1, b2 = st.columns(2)
        if b1.button("Log View", key="collab_log_view", width="stretch"):
            if use_local_api:
                res = api_post_json(
                    api_base_url,
                    "/collab/view",
                    {"user_id": current_user, "area": area, "context": log_context},
                )
                if res["ok"]:
                    st.success("View logged via API.")
                else:
                    st.error(f"API error: {res['error']}")
            else:
                log_view(db_path, current_user, area, log_context)
                st.success("View logged.")
        if b2.button("Log Edit", key="collab_log_edit", width="stretch"):
            if use_local_api:
                res = api_post_json(
                    api_base_url,
                    "/collab/edit",
                    {"user_id": current_user, "area": area, "summary": edit_summary},
                )
                if res["ok"]:
                    st.success("Edit logged via API.")
                else:
                    st.error(f"API error: {res['error']}")
            else:
                log_edit(db_path, current_user, area, edit_summary)
                st.success("Edit logged.")

        st.markdown("#### Comments")
        comment_text = st.text_area(
            "Comment text",
            value="",
            height=80,
            key="collab_comment_text",
            placeholder="Add context for teammates...",
        )
        reply_to = st.text_input(
            "Reply to comment ID (optional)", value="", key="collab_reply_to"
        )
        if st.button("Add Comment", key="collab_add_comment"):
            if not comment_text.strip():
                st.warning("Comment text is required.")
            else:
                if use_local_api:
                    res = api_post_json(
                        api_base_url,
                        "/collab/comments",
                        {
                            "user_id": current_user,
                            "area": area,
                            "text": comment_text.strip(),
                            "reply_to": reply_to.strip() or None,
                        },
                    )
                    if res["ok"]:
                        comment_id = res["data"].get("comment_id", "unknown")
                        st.success(f"Comment created: {comment_id}")
                    else:
                        st.error(f"API error: {res['error']}")
                else:
                    comment_id = add_comment(
                        db_path,
                        current_user,
                        area,
                        comment_text.strip(),
                        reply_to.strip() or None,
                    )
                    st.success(f"Comment created: {comment_id}")

        st.markdown("#### Proposed Edits")
        pcol1, pcol2 = st.columns(2)
        proposal_title = pcol1.text_input(
            "Proposal title",
            value="",
            key="collab_proposal_title",
            placeholder="Example: Increase incubation timeout",
        )
        proposal_change = pcol2.text_input(
            "Proposed change",
            value="",
            key="collab_proposal_change",
            placeholder="incubation_timeout_sec: 900 -> 1200",
        )
        if st.button("Submit Proposed Edit", key="collab_add_proposal"):
            if not proposal_title.strip() or not proposal_change.strip():
                st.warning("Both title and proposed change are required.")
            else:
                if use_local_api:
                    res = api_post_json(
                        api_base_url,
                        "/collab/proposals",
                        {
                            "user_id": current_user,
                            "area": area,
                            "title": proposal_title.strip(),
                            "change": proposal_change.strip(),
                        },
                    )
                    if res["ok"]:
                        proposal_id = res["data"].get("proposal_id", "unknown")
                        st.success(f"Proposal created: {proposal_id}")
                    else:
                        st.error(f"API error: {res['error']}")
                else:
                    proposal_id = add_proposal(
                        db_path,
                        current_user,
                        area,
                        proposal_title.strip(),
                        proposal_change.strip(),
                    )
                    st.success(f"Proposal created: {proposal_id}")

        with st.expander("Review Proposed Edit"):
            review_id = st.text_input(
                "Proposal ID", value="", key="collab_review_id", placeholder="PRP-..."
            )
            decision = st.selectbox(
                "Decision", ["approve", "reject"], key="collab_review_decision"
            )
            review_note = st.text_area(
                "Review note", value="", height=70, key="collab_review_note"
            )
            if st.button("Submit Review", key="collab_submit_review"):
                if not review_id.strip():
                    st.warning("Proposal ID is required.")
                else:
                    if use_local_api:
                        res = api_post_json(
                            api_base_url,
                            f"/collab/proposals/{review_id.strip()}/review",
                            {
                                "reviewer_id": current_user,
                                "decision": decision,
                                "note": review_note.strip(),
                            },
                        )
                        if res["ok"]:
                            st.success("Proposal review submitted via API.")
                        else:
                            st.error(f"API error: {res['error']}")
                    else:
                        ok = review_proposal(
                            db_path,
                            review_id.strip(),
                            reviewer_id=current_user,
                            decision=decision,
                            note=review_note.strip(),
                        )
                        if ok:
                            st.success("Proposal review submitted.")
                        else:
                            st.error("Proposal ID not found.")

        st.markdown("#### Activity Feed")
        feed_limit = st.slider("Feed rows", min_value=10, max_value=200, value=50)
        if use_local_api:
            feed_res = api_get_json(
                api_base_url, "/collab/activity", {"limit": feed_limit}
            )
            if feed_res["ok"]:
                feed = feed_res["data"].get("items", [])
            else:
                st.error(f"API error: {feed_res['error']}")
                feed = []
        else:
            feed = list_activity(db_path, limit=feed_limit, area=None)
        if feed:
            st.dataframe(pd.DataFrame(feed), width="stretch")
        else:
            st.caption("No activity yet.")

        st.markdown("#### Open Comments")
        if use_local_api:
            comments_res = api_get_json(
                api_base_url, "/collab/comments", {"limit": 100}
            )
            if comments_res["ok"]:
                comments = comments_res["data"].get("items", [])
            else:
                st.error(f"API error: {comments_res['error']}")
                comments = []
        else:
            comments = list_comments(db_path, limit=100, area=None)
        if comments:
            st.dataframe(pd.DataFrame(comments), width="stretch")
        else:
            st.caption("No comments yet.")

        st.markdown("#### Proposed Edits")
        proposal_status = st.selectbox(
            "Filter proposals by status",
            ["all", "open", "approved", "rejected"],
            key="collab_proposal_status_filter",
        )
        if use_local_api:
            proposals_res = api_get_json(
                api_base_url,
                "/collab/proposals",
                {"limit": 100, "status": proposal_status},
            )
            if proposals_res["ok"]:
                proposals = proposals_res["data"].get("items", [])
            else:
                st.error(f"API error: {proposals_res['error']}")
                proposals = []
        else:
            proposals = list_proposals(
                db_path, limit=100, area=None, status=proposal_status
            )
        if proposals:
            st.dataframe(pd.DataFrame(proposals), width="stretch")
        else:
            st.caption("No proposals yet.")


def main() -> None:
    supported, compat_msg = require_supported_python()
    if not supported:
        st.set_page_config(page_title="Lab QC & Ops Dashboard", layout="wide")
        st.error(compat_msg)
        st.info("Please switch to a supported Python 3.x environment, reinstall dependencies, and restart the app.")
        st.stop()

    st.set_page_config(page_title="Lab QC & Ops Dashboard", layout="wide")
    init_process_state()
    render_hotkey_bindings()
    apply_global_ui_style()

    st.title("Lab QC & Ops Dashboard")
    st.caption("Designed for stressed lab workflows: minimal clicks, clear outputs, and guided next steps.")
    st.caption("Hotkeys: Ctrl+R starts Daily QC in background, Ctrl+E stops selected process.")

    with st.sidebar:
        st.header("Environment")
        is_power_user_mode = st.session_state.get("mode_pref", "Streamlined (recommended)") == "In-Lab Custom"
        render_hover_tooltip_label(
            "Collaboration user",
            mode_aware_tooltip(
                "This is the name that appears when you leave notes or edits.",
                "User identity attached to collaboration activity logs, comments, and proposals.",
                is_power_user_mode,
            ),
        )
        collab_user = st.text_input("Collaboration user", value="angus", label_visibility="collapsed")
        render_hover_tooltip_label(
            "Local API base URL",
            mode_aware_tooltip(
                "This is the local address the app uses to talk to the lab service running on this machine/network.",
                "Base URL for local FastAPI endpoints used by collaboration and health checks.",
                is_power_user_mode,
            ),
        )
        local_api_url = st.text_input(
            "Local API base URL",
            value="http://127.0.0.1:8010",
            label_visibility="collapsed",
        )
        render_hover_tooltip_label(
            "Python executable",
            mode_aware_tooltip(
                "This is which Python installation the app should use to run analysis steps.",
                "Absolute interpreter path used to execute Python pipeline commands.",
                is_power_user_mode,
            ),
        )
        python_exe = st.text_input(
            "Python executable",
            value=default_python_exe(),
            label_visibility="collapsed",
        )
        render_hover_tooltip_label(
            "Rscript executable",
            mode_aware_tooltip(
                "This is the R command the app uses for R-based analysis steps.",
                "Rscript binary path/command used by METAFlux and other R tasks.",
                is_power_user_mode,
            ),
        )
        rscript_exe = st.text_input(
            "Rscript executable",
            value=default_rscript_exe(),
            label_visibility="collapsed",
        )
        render_hover_tooltip_label(
            "Project root",
            mode_aware_tooltip(
                "Main project folder. The app reads inputs and saves outputs relative to this folder.",
                "Workspace root path used to resolve configs, scripts, outputs, and run artifacts.",
                is_power_user_mode,
            ),
        )
        project_root = st.text_input(
            "Project root",
            value=str(PROJECT_ROOT),
            label_visibility="collapsed",
        )
        mode_options = ["Streamlined (recommended)", "In-Lab Custom"]
        profile_options = OPERATOR_PROFILES
        default_mode = st.session_state.get("mode_pref", "Streamlined (recommended)")
        default_profile = st.session_state.get("operator_profile_pref", "DeltaV Familiar")
        default_lab_language = st.session_state.get("lab_language_pref", True)
        render_hover_tooltip_label(
            "Training mode (new user onboarding)",
            "Applies beginner-safe defaults and simplified signposting.",
        )
        training_mode = st.toggle(
            "Training mode (new user onboarding) switch",
            value=st.session_state.get("training_mode", False),
            label_visibility="collapsed",
        )
        st.session_state["training_mode"] = training_mode
        if training_mode:
            default_mode = "Streamlined (recommended)"
            default_profile = "New to Lab / No DeltaV"
            default_lab_language = True
        is_power_user_mode = default_mode == "In-Lab Custom"
        render_hover_tooltip_label(
            "Interface mode",
            mode_aware_tooltip(
                "Pick how you want to use this app. Streamlined walks you through the main steps. In-Lab Custom gives you all controls at once.",
                "Select UI complexity level. Streamlined is a guided linear workflow; In-Lab Custom exposes full tab-level control surface.",
                is_power_user_mode,
            ),
        )
        mode = default_mode
        mode_col_a, mode_col_b = st.columns(2)
        if mode_col_a.button(
            "Streamlined (recommended)",
            key="mode_streamlined_option",
            type="primary" if default_mode == "Streamlined (recommended)" else "secondary",
            help=mode_aware_tooltip(
                "Best for most people. It walks you step-by-step: run checks, review results, then export.",
                "Guided onboarding flow: Daily QC -> Readiness -> ELN/LIMS Export.",
                is_power_user_mode,
            ),
            use_container_width=True,
        ):
            mode = "Streamlined (recommended)"
        elif mode_col_b.button(
            "In-Lab Custom",
            key="mode_custom_option",
            type="primary" if default_mode == "In-Lab Custom" else "secondary",
            help=mode_aware_tooltip(
                "Shows all tools and tabs so you can control every step yourself.",
                "Power-user layout with full tabs and advanced controls for custom workflows.",
                is_power_user_mode,
            ),
            use_container_width=True,
        ):
            mode = "In-Lab Custom"
        is_power_user_mode = mode == "In-Lab Custom"
        render_hover_tooltip_label(
            "Lab Language mode",
            mode_aware_tooltip(
                "Use simpler wording and everyday lab language in labels and instructions.",
                "Prioritize plain in-lab wording over technical terminology in labels and guidance.",
                is_power_user_mode,
            ),
        )
        use_lab_language = st.toggle(
            "Lab Language mode switch",
            value=bool(default_lab_language),
            label_visibility="collapsed",
        )
        render_hover_tooltip_label(
            "Operator profile",
            mode_aware_tooltip(
                "Choose the guidance style that matches your background in the lab.",
                "Switch onboarding guidance between experienced control-room users and new operators.",
                is_power_user_mode,
            ),
        )
        operator_profile = st.selectbox(
            "Operator profile selector",
            profile_options,
            index=profile_options.index(default_profile),
            label_visibility="collapsed",
        )
        st.session_state["mode_pref"] = mode
        st.session_state["operator_profile_pref"] = operator_profile
        st.session_state["lab_language_pref"] = bool(use_lab_language)
        tooltip_power_user_mode = mode == "In-Lab Custom"
        st.markdown("---")
        render_glutamate_reminder()
        render_data_preservation_reminder()
        st.markdown("---")
        st.write("Tip: keep defaults on the lab machine unless paths changed.")

    root = Path(project_root).expanduser().resolve()
    host_platform = detect_host_platform()
    api_health = api_get_json(local_api_url, "/health")
    use_local_api = bool(api_health.get("ok"))

    with st.container(border=True):
        st.subheader("Host Platform & Lab Implement Auto-Connect")
        st.caption(f"Detected operating system: {host_platform['label']}")
        st.caption(
            "Local API: "
            + ("connected" if use_local_api else "offline (using direct DB fallback)")
        )
        st.caption("Auto-connect config adapts instrument watch folders for this OS and keeps Google mirror paths aligned.")
        if st.button("Auto-configure Lab Implements for this OS", key="auto_configure_lab_implements"):
            cfg_path = root / "config.validation_ops.yaml"
            if not cfg_path.exists():
                st.error(f"Config not found: {cfg_path}")
            else:
                result = auto_configure_lab_implements(cfg_path, host_platform["id"], root)
                st.success("Lab implement auto-connect configuration updated.")
                st.caption(f"Config updated: {result['config']}")
                st.caption(f"Fallback dropbox: {result['fallback_dropbox']}")
                st.write("Active instrument source folders:")
                st.json(result["sources"])

        if st.button("Run Bridge Test (--once)", key="bridge_test_once"):
            cfg_path = root / "config.validation_ops.yaml"
            if not cfg_path.exists():
                st.error(f"Config not found: {cfg_path}")
            else:
                cmd = [
                    python_exe,
                    str(root / "instrument_bridge.py"),
                    "--config",
                    str(cfg_path),
                    "--once",
                ]
                result = run_command(cmd, cwd=root)
                show_command_result("Bridge Test (--once)", result)

                stdout_text = result.get("stdout", "") or ""
                stderr_text = result.get("stderr", "") or ""
                if result.get("ok"):
                    if "Pulled" in stdout_text and "Google Drive mirror" in stdout_text:
                        diagnosis = "bridge_sync_success"
                    elif "Detected" in stdout_text and "Running pipeline" in stdout_text:
                        diagnosis = "bridge_detected_new_images"
                    elif "No new instrument images" in stdout_text:
                        diagnosis = "bridge_no_new_images"
                    else:
                        diagnosis = "bridge_test_ok"
                else:
                    diagnosis = "bridge_test_failed"

                events_path = append_webui_telemetry_event(
                    root=root,
                    event_type="bridge_test_once",
                    diagnosis=diagnosis,
                    details={
                        "host_platform": host_platform["label"],
                        "config_path": str(cfg_path),
                        "returncode": result.get("returncode"),
                        "stdout_tail": "\n".join(stdout_text.splitlines()[-30:]),
                        "stderr_tail": "\n".join(stderr_text.splitlines()[-30:]),
                        **collect_host_control_diagnostics(),
                    },
                )
                st.info(f"Telemetry logged: {events_path}")

            render_webui_telemetry_panel(root)
    latest_run = latest_run_dir(root)
    py_summary = python_runtime_summary(python_exe)
    run_summary = latest_run_summary(latest_run)

    with st.container(border=True):
        st.subheader("System Status")
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Project folder", "Found" if root.exists() else "Missing", root.name if root.exists() else "Check project root")
        col_b.metric("Python", py_summary["value"], py_summary["delta"])
        col_c.metric("Latest run", run_summary["value"], run_summary["delta"])
        st.caption(f"Python executable: {py_summary['detail']}")
        st.caption(f"Latest run details: {run_summary['detail']}")
        st.caption(f"Latest run snapshot: {run_summary['snapshot']}")
        if run_summary.get("severity") == "success":
            st.success(f"Run diagnosis: {run_summary['diagnosis']}")
        elif run_summary.get("severity") == "warning":
            st.warning(f"Run diagnosis: {run_summary['diagnosis']}")
        elif run_summary.get("severity") == "error":
            st.error(f"Run diagnosis: {run_summary['diagnosis']}")
        else:
            st.info(f"Run diagnosis: {run_summary['diagnosis']}")

    if operator_profile == "New to Lab / No DeltaV":
        if mode != "Streamlined (recommended)":
            st.info(
                "Profile tip: 'New to Lab / No DeltaV' is best with Streamlined mode for step-by-step guidance."
            )
        if not use_lab_language:
            st.info(
                "Profile tip: turn on 'Lab Language mode' to reduce jargon for new operators."
            )
    if training_mode:
        st.success(
            "Training mode is ON: simplified defaults applied. Follow the Guided Workflow section from left to right."
        )

    render_operator_walkthrough(
        profile=operator_profile,
        use_lab_language=use_lab_language,
        latest_run=latest_run,
        use_local_api=use_local_api,
    )

    render_shift_dashboard(root, python_exe)
    render_process_monitor_with_autorefresh()

    if mode == "Streamlined (recommended)":
        render_glutamate_reminder()
        render_data_preservation_reminder()
        st.markdown(f"### {ui_text(use_lab_language, 'Guided Workflow (First Run)')}")
        st.write("Use these three steps in order. Each step tells you exactly what to do next.")
        render_streamlined_signpost(latest_run)
        focus_step = render_start_here_navigator()

        step1, step2, step3 = st.columns(3)

        with step1:
            if focus_step == "1":
                st.success("Focused step: start here.")
            render_section_glance_image("Daily QC", "🔬", "#0f6b62")
            st.markdown(f"#### 1) {ui_text(use_lab_language, 'Run Daily QC')}")
            render_section_help("Daily QC")
            cfg = root / "config.validation_ops.yaml"
            cal_enabled = st.checkbox(
                "Enable spectral calibration",
                value=True,
                key="stream_cal_enabled",
                help=mode_aware_tooltip(
                    "Helps make photos look more consistent before scoring quality.",
                    "Applies color/illumination normalization before QC scoring to reduce instrument lighting variation.",
                    tooltip_power_user_mode,
                ),
            )
            cal_wb_mode = st.selectbox(
                "Calibration white balance mode",
                ["grayworld", "reference_patch"],
                index=0,
                key="stream_cal_wb",
                help=mode_aware_tooltip(
                    "Pick how the app balances color. Use grayworld for normal images; use reference patch if your image includes one.",
                    "Choose white-balance estimation mode: grayworld for general scenes, reference_patch when a known calibration patch is present.",
                    tooltip_power_user_mode,
                ),
            )
            cal_gamma = st.slider(
                "Calibration gamma",
                min_value=0.5,
                max_value=2.0,
                value=1.0,
                step=0.05,
                key="stream_cal_gamma",
                help=mode_aware_tooltip(
                    "Changes image brightness in the middle tones. Lower is darker, higher is brighter.",
                    "Adjusts brightness response during calibration. Lower values darken mid-tones; higher values brighten them.",
                    tooltip_power_user_mode,
                ),
            )
            render_step_cues(
                input_text="Microscopy image set + calibration mode",
                action_text="Run Daily QC",
                output_text="records.csv, run status, and quality signals",
            )
            if st.button(
                ui_text(use_lab_language, "Start Daily QC"),
                type="primary",
                width="stretch",
                help=mode_aware_tooltip(
                    "Start the full quality check now and wait for results here.",
                    "Runs the full Daily QC pipeline in the foreground and returns status, records, and quality signals when finished.",
                    tooltip_power_user_mode,
                ),
            ):
                runtime_cfg_path = root / "_tmp_webui_runtime_config.yaml"
                runtime_cfg = write_runtime_config(
                    base_config_path=cfg,
                    runtime_overrides={
                        "spectral_calibration": {
                            "enabled": bool(cal_enabled),
                            "white_balance_mode": cal_wb_mode,
                            "gamma_correction": float(cal_gamma),
                        }
                    },
                    out_path=runtime_cfg_path,
                )
                cmd = [python_exe, str(root / "run_pipeline.py"), "--config", str(runtime_cfg)]
                result = run_command(cmd, cwd=root)
                show_command_result(ui_text(use_lab_language, "Daily QC"), result)
                payload = parse_json_tail(result.get("stdout", ""))
                if payload and payload.get("output_root"):
                    st.info(f"Output saved to: {payload['output_root']}")
                    st.success("Next step: open Step 2 to review readiness.")
            if st.button(
                "Start Daily QC (BG)",
                width="stretch",
                help=mode_aware_tooltip(
                    "Start quality checks in the background so you can keep using the app.",
                    "Starts Daily QC in the background; track execution in the process monitor.",
                    tooltip_power_user_mode,
                ),
            ):
                runtime_cfg_path = root / "_tmp_webui_runtime_config_bg.yaml"
                runtime_cfg = write_runtime_config(
                    base_config_path=cfg,
                    runtime_overrides={
                        "spectral_calibration": {
                            "enabled": bool(cal_enabled),
                            "white_balance_mode": cal_wb_mode,
                            "gamma_correction": float(cal_gamma),
                        }
                    },
                    out_path=runtime_cfg_path,
                )
                process_id = start_managed_process(
                    name="Daily QC",
                    command=[python_exe, str(root / "run_pipeline.py"), "--config", str(runtime_cfg)],
                    cwd=root,
                )
                st.success(f"Background process started: {process_id}")
            if st.button(
                "Replay Failed Items",
                width="stretch",
                help=mode_aware_tooltip(
                    "Only re-run items that failed last time instead of redoing everything.",
                    "Re-runs only failed items from prior execution to recover without repeating a full batch.",
                    tooltip_power_user_mode,
                ),
            ):
                checkpoint_path = root / "output_caption_microscopy_full_bliplarge" / "checkpoint.json"
                if not checkpoint_path.exists() and not any((d / "failed_records.json").exists() for d in run_output_dirs(root)):
                    st.warning("No prior failed items found to replay yet.")
                else:
                    replay_result = replay_failed_run(root, python_exe, cfg)
                    show_command_result("Replay Failed Items", replay_result)

        with step2:
            if focus_step == "2":
                st.success("Focused step: review readiness now.")
            render_section_glance_image("Readiness", "📊", "#3d6fb6")
            st.markdown(f"#### 2) {ui_text(use_lab_language, 'Readiness')}")
            render_section_help("Readiness")
            current_latest = latest_run_dir(root)
            records_csv = (current_latest / "records.csv") if current_latest else (root / "output_caption_microscopy_full_bliplarge" / "records.csv")
            render_step_cues(
                input_text="Latest records.csv from Step 1",
                action_text="Compute Readiness",
                output_text="Ready/Review/Hold triage table",
            )
            if st.button(
                ui_text(use_lab_language, "Compute Readiness"),
                width="stretch",
                help=mode_aware_tooltip(
                    "Sorts results into ready, review, or hold and tells you why.",
                    "Calculates sample readiness classes from the latest run and surfaces ready/review/hold rationale.",
                    tooltip_power_user_mode,
                ),
            ):
                readiness_preview(records_csv)
                st.success("Next step: export ELN/LIMS package in Step 3.")

        with step3:
            if focus_step == "3":
                st.success("Focused step: finalize package export.")
            render_section_glance_image("ELN/LIMS Export", "📦", "#7b4ea3")
            st.markdown(f"#### 3) {ui_text(use_lab_language, 'ELN/LIMS Export')}")
            render_section_help("ELN/LIMS Export")
            preferred_run = default_cellmedia_run_dir(root)
            run_dir = preferred_run if preferred_run else (root / "output_caption_microscopy_full_bliplarge")
            out_dir = root / "eln_packages"
            render_step_cues(
                input_text="Validated run output folder",
                action_text="Export ELN/LIMS Package",
                output_text="Timestamped package folder + zip for handoff",
            )
            export_ready = render_qc_checklist_gate("streamlined_export")
            if st.button(
                ui_text(use_lab_language, "Export Package"),
                width="stretch",
                disabled=not export_ready,
                help=mode_aware_tooltip(
                    "Creates a handoff package you can share with the team and records.",
                    "Builds a timestamped ELN/LIMS-ready package from validated outputs for handoff, traceability, and downstream review.",
                    tooltip_power_user_mode,
                ),
            ):
                cmd = [
                    python_exe,
                    str(root / "export_eln_lims_package.py"),
                    "--run-dir",
                    str(run_dir),
                    "--out-dir",
                    str(out_dir),
                ]
                result = run_command(cmd, cwd=root)
                show_command_result(ui_text(use_lab_language, "ELN/LIMS Export"), result)
                payload = parse_json_tail(result.get("stdout", ""))
                if payload and payload.get("package_dir"):
                    st.info(f"Package folder: {payload['package_dir']}")
                st.success("Workflow complete for today.")
            if st.button(
                "Create Run Fingerprint",
                width="stretch",
                help=mode_aware_tooltip(
                    "Save a run identity file so you can prove exactly what was run.",
                    "Generates an audit fingerprint with file hashes, environment details, and git state for reproducibility.",
                    tooltip_power_user_mode,
                ),
            ):
                target_run = latest_run_dir(root)
                if not target_run:
                    st.warning("No run folder available yet.")
                else:
                    fp = create_run_fingerprint(target_run, Path(cfg), python_exe, root)
                    st.success(f"Run fingerprint saved: {fp}")

        st.markdown("---")
        st.markdown("---")
        if training_mode:
            st.markdown("### Next Features (after you complete Steps 1-3)")
            st.caption(
                "Training mode hides advanced controls by default. Expand when you're ready."
            )
            with st.expander("Open advanced features", expanded=False):
                st.markdown("#### Optional Weekly Tasks")
                col_w1, col_w2 = st.columns(2)
                with col_w1:
                    if st.button(
                        ui_text(use_lab_language, "Generate Weekly PI Summary"),
                        help=mode_aware_tooltip(
                            "Create a weekly summary report from recent runs.",
                            "Generate weekly markdown/json summary across output_* runs.",
                            tooltip_power_user_mode,
                        ),
                    ):
                        weekly_md = str(root / "weekly_pi_summary.md")
                        cmd = [
                            python_exe,
                            str(root / "generate_weekly_pi_summary.py"),
                            "--runs-root",
                            str(root),
                            "--pattern",
                            "output_*",
                            "--output",
                            weekly_md,
                        ]
                        result = run_command(cmd, cwd=root)
                        show_command_result(ui_text(use_lab_language, "Weekly PI Summary"), result)
                    if st.button(
                        "Generate Weekly PI Summary (BG)",
                        help=mode_aware_tooltip(
                            "Build the weekly summary in the background so you can keep working.",
                            "Run weekly summary in background and track in process bars.",
                            tooltip_power_user_mode,
                        ),
                    ):
                        weekly_md = str(root / "weekly_pi_summary.md")
                        process_id = start_managed_process(
                            name="Weekly PI Summary",
                            command=[
                                python_exe,
                                str(root / "generate_weekly_pi_summary.py"),
                                "--runs-root",
                                str(root),
                                "--pattern",
                                "output_*",
                                "--output",
                                weekly_md,
                            ],
                            cwd=root,
                        )
                        st.success(f"Background process started: {process_id}")
                with col_w2:
                    if st.button(
                        ui_text(use_lab_language, "Run Benchmark Drift Suite"),
                        help=mode_aware_tooltip(
                            "Run extra quality checks to compare performance over time.",
                            "Run benchmark and drift checks for model governance.",
                            tooltip_power_user_mode,
                        ),
                    ):
                        cmd = [python_exe, str(root / "run_benchmark_suite.py"), "--python", python_exe, "--project-root", str(root)]
                        result = run_command(cmd, cwd=root)
                        show_command_result(ui_text(use_lab_language, "Run Benchmark Drift Suite"), result)
                    if st.button(
                        "Run Benchmark Drift Suite (BG)",
                        help=mode_aware_tooltip(
                            "Run these extra checks in the background.",
                            "Run benchmark drift suite in background.",
                            tooltip_power_user_mode,
                        ),
                    ):
                        process_id = start_managed_process(
                            name="Benchmark Drift Suite",
                            command=[python_exe, str(root / "run_benchmark_suite.py"), "--python", python_exe, "--project-root", str(root)],
                            cwd=root,
                        )
                        st.success(f"Background process started: {process_id}")

                st.markdown("#### Telemetry Export")
                telemetry_team_md = str(root / "telemetry_team_report.md")
                telemetry_ai_json = str(root / "telemetry_ai_report.json")
                if st.button(
                    "Export Telemetry (Team + AI)",
                    help=mode_aware_tooltip(
                        "Export status reports for people and for automation tools.",
                        "Create team-readable markdown plus AI-crawlable JSON telemetry exports.",
                        tooltip_power_user_mode,
                    ),
                ):
                    cmd = [
                        python_exe,
                        str(root / "export_telemetry_reports.py"),
                        "--runs-root",
                        str(root),
                        "--team-output",
                        telemetry_team_md,
                        "--ai-output",
                        telemetry_ai_json,
                        "--pattern",
                        "output_*",
                        "--window-days",
                        "30",
                    ]
                    result = run_command(cmd, cwd=root)
                    show_command_result("Telemetry Export", result)
                    if result.get("ok"):
                        st.info(f"Team report: {telemetry_team_md}")
                        st.info(f"AI report: {telemetry_ai_json}")
                if st.button(
                    "Export Telemetry (BG)",
                    help=mode_aware_tooltip(
                        "Export those reports in the background.",
                        "Run telemetry export in background.",
                        tooltip_power_user_mode,
                    ),
                ):
                    process_id = start_managed_process(
                        name="Telemetry Export",
                        command=[
                            python_exe,
                            str(root / "export_telemetry_reports.py"),
                            "--runs-root",
                            str(root),
                            "--team-output",
                            telemetry_team_md,
                            "--ai-output",
                            telemetry_ai_json,
                            "--pattern",
                            "output_*",
                            "--window-days",
                            "30",
                        ],
                        cwd=root,
                    )
                    st.success(f"Background process started: {process_id}")

                st.markdown("#### METAFlux Analyzer")
                metaflux_cfg = st.text_input(
                    "METAFlux config (.json)",
                    value=str(root / "metaflux_config.example.json"),
                    key="stream_metaflux_cfg",
                )
                if st.button(
                    "Run METAFlux Analyzer",
                    help=mode_aware_tooltip(
                        "Run the metabolism analysis and generate charts from your input data.",
                        "Run nutrient flux + pathway heatmap from expression data.",
                        tooltip_power_user_mode,
                    ),
                ):
                    result = run_metaflux_from_webapp(root, rscript_exe, Path(metaflux_cfg))
                    show_command_result("METAFlux Analyzer", result)
                    if result.get("ok"):
                        st.success("METAFlux run completed. Check configured output_dir for plots and CSV outputs.")
                if st.button(
                    "Run METAFlux Analyzer (BG)",
                    help=mode_aware_tooltip(
                        "Run metabolism analysis in the background.",
                        "Run METAFlux analyzer in background.",
                        tooltip_power_user_mode,
                    ),
                ):
                    launcher = root / "run_metaflux_analyzer.R"
                    cfg_path = Path(metaflux_cfg)
                    if not launcher.exists():
                        st.error(f"METAFlux launcher not found: {launcher}")
                    elif not cfg_path.exists():
                        st.error(f"METAFlux config not found: {cfg_path}")
                    else:
                        process_id = start_managed_process(
                            name="METAFlux Analyzer",
                            command=[rscript_exe, str(launcher), "--config", str(cfg_path)],
                            cwd=root,
                        )
                        st.success(f"Background process started: {process_id}")

                st.markdown("---")
                st.markdown("### Alerts & Trends")
                render_section_help("Alerts & Trends")
                low_q_threshold = st.slider(
                    "Alert threshold: low-quality rate",
                    min_value=0.05,
                    max_value=0.60,
                    value=0.25,
                    step=0.01,
                    help=mode_aware_tooltip(
                        "Set how quickly the app should warn you about low-quality results. Lower values warn sooner.",
                        "Alert triggers when low-quality fraction exceeds this value. Lower threshold = higher sensitivity.",
                        tooltip_power_user_mode,
                    ),
                )
                alerts = compute_lab_alerts(root, max_low_quality_rate=low_q_threshold)
                if not alerts:
                    st.success("No active lab alerts from latest run.")
                else:
                    for alert in alerts:
                        if alert["severity"] == "high":
                            st.error(alert["message"])
                        else:
                            st.warning(alert["message"])

                trend_days = st.selectbox(
                    "Trend window",
                    [7, 30],
                    index=1,
                    help=mode_aware_tooltip(
                        "Choose how many days to include in trend charts.",
                        "Number of recent days included in trend charts.",
                        tooltip_power_user_mode,
                    ),
                )
                trend_df = collect_run_trends(root, day_window=int(trend_days))
                if trend_df.empty:
                    st.caption("No recent run data available for trend charts yet.")
                else:
                    st.line_chart(trend_df.set_index("timestamp")[["low_quality_rate", "median_caption_quality", "spectral_drift_rate"]])
                    st.bar_chart(trend_df.set_index("timestamp")[["processed_count", "failed_count", "hold_count"]])

                st.markdown("---")
                render_section_glance_image("Cell/Media Visualizations", "🧫", "#0b7285")
                st.markdown("### Cell/Media Visualizations")
                render_section_help("Cell/Media Visualizations")
                current_run = default_cellmedia_run_dir(root)
                if current_run:
                    render_cell_media_visualization(current_run)
                else:
                    st.caption("No run directory available yet for cell/media visualizations.")
        else:
            st.markdown(f"### {ui_text(use_lab_language, 'Optional Weekly Tasks')}")
            col_w1, col_w2 = st.columns(2)
            with col_w1:
                if st.button(
                    ui_text(use_lab_language, "Generate Weekly PI Summary"),
                    help=mode_aware_tooltip(
                        "Create a weekly summary report from recent runs.",
                        "Generate weekly markdown/json summary across output_* runs.",
                        tooltip_power_user_mode,
                    ),
                ):
                    weekly_md = str(root / "weekly_pi_summary.md")
                    cmd = [
                        python_exe,
                        str(root / "generate_weekly_pi_summary.py"),
                        "--runs-root",
                        str(root),
                        "--pattern",
                        "output_*",
                        "--output",
                        weekly_md,
                    ]
                    result = run_command(cmd, cwd=root)
                    show_command_result(ui_text(use_lab_language, "Weekly PI Summary"), result)
                if st.button(
                    "Generate Weekly PI Summary (BG)",
                    help=mode_aware_tooltip(
                        "Build the weekly summary in the background so you can keep working.",
                        "Run weekly summary in background and track in process bars.",
                        tooltip_power_user_mode,
                    ),
                ):
                    weekly_md = str(root / "weekly_pi_summary.md")
                    process_id = start_managed_process(
                        name="Weekly PI Summary",
                        command=[
                            python_exe,
                            str(root / "generate_weekly_pi_summary.py"),
                            "--runs-root",
                            str(root),
                            "--pattern",
                            "output_*",
                            "--output",
                            weekly_md,
                        ],
                        cwd=root,
                    )
                    st.success(f"Background process started: {process_id}")
            with col_w2:
                if st.button(
                    ui_text(use_lab_language, "Run Benchmark Drift Suite"),
                    help=mode_aware_tooltip(
                        "Run extra quality checks to compare performance over time.",
                        "Run benchmark and drift checks for model governance.",
                        tooltip_power_user_mode,
                    ),
                ):
                    cmd = [python_exe, str(root / "run_benchmark_suite.py"), "--python", python_exe, "--project-root", str(root)]
                    result = run_command(cmd, cwd=root)
                    show_command_result(ui_text(use_lab_language, "Run Benchmark Drift Suite"), result)
                if st.button(
                    "Run Benchmark Drift Suite (BG)",
                    help=mode_aware_tooltip(
                        "Run these extra checks in the background.",
                        "Run benchmark drift suite in background.",
                        tooltip_power_user_mode,
                    ),
                ):
                    process_id = start_managed_process(
                        name="Benchmark Drift Suite",
                        command=[python_exe, str(root / "run_benchmark_suite.py"), "--python", python_exe, "--project-root", str(root)],
                        cwd=root,
                    )
                    st.success(f"Background process started: {process_id}")

            st.markdown("#### Telemetry Export")
            telemetry_team_md = str(root / "telemetry_team_report.md")
            telemetry_ai_json = str(root / "telemetry_ai_report.json")
            if st.button(
                "Export Telemetry (Team + AI)",
                help=mode_aware_tooltip(
                    "Export status reports for people and for automation tools.",
                    "Create team-readable markdown plus AI-crawlable JSON telemetry exports.",
                    tooltip_power_user_mode,
                ),
            ):
                cmd = [
                    python_exe,
                    str(root / "export_telemetry_reports.py"),
                    "--runs-root",
                    str(root),
                    "--team-output",
                    telemetry_team_md,
                    "--ai-output",
                    telemetry_ai_json,
                    "--pattern",
                    "output_*",
                    "--window-days",
                    "30",
                ]
                result = run_command(cmd, cwd=root)
                show_command_result("Telemetry Export", result)
                if result.get("ok"):
                    st.info(f"Team report: {telemetry_team_md}")
                    st.info(f"AI report: {telemetry_ai_json}")
            if st.button(
                "Export Telemetry (BG)",
                help=mode_aware_tooltip(
                    "Export those reports in the background.",
                    "Run telemetry export in background.",
                    tooltip_power_user_mode,
                ),
            ):
                process_id = start_managed_process(
                    name="Telemetry Export",
                    command=[
                        python_exe,
                        str(root / "export_telemetry_reports.py"),
                        "--runs-root",
                        str(root),
                        "--team-output",
                        telemetry_team_md,
                        "--ai-output",
                        telemetry_ai_json,
                        "--pattern",
                        "output_*",
                        "--window-days",
                        "30",
                    ],
                    cwd=root,
                )
                st.success(f"Background process started: {process_id}")

            st.markdown("#### METAFlux Analyzer")
            metaflux_cfg = st.text_input(
                "METAFlux config (.json)",
                value=str(root / "metaflux_config.example.json"),
                key="stream_metaflux_cfg",
            )
            if st.button(
                "Run METAFlux Analyzer",
                help=mode_aware_tooltip(
                    "Run the metabolism analysis and generate charts from your input data.",
                    "Run nutrient flux + pathway heatmap from expression data.",
                    tooltip_power_user_mode,
                ),
            ):
                result = run_metaflux_from_webapp(root, rscript_exe, Path(metaflux_cfg))
                show_command_result("METAFlux Analyzer", result)
                if result.get("ok"):
                    st.success("METAFlux run completed. Check configured output_dir for plots and CSV outputs.")
            if st.button(
                "Run METAFlux Analyzer (BG)",
                help=mode_aware_tooltip(
                    "Run metabolism analysis in the background.",
                    "Run METAFlux analyzer in background.",
                    tooltip_power_user_mode,
                ),
            ):
                launcher = root / "run_metaflux_analyzer.R"
                cfg_path = Path(metaflux_cfg)
                if not launcher.exists():
                    st.error(f"METAFlux launcher not found: {launcher}")
                elif not cfg_path.exists():
                    st.error(f"METAFlux config not found: {cfg_path}")
                else:
                    process_id = start_managed_process(
                        name="METAFlux Analyzer",
                        command=[rscript_exe, str(launcher), "--config", str(cfg_path)],
                        cwd=root,
                    )
                    st.success(f"Background process started: {process_id}")

            st.markdown("---")
            st.markdown("### Alerts & Trends")
            render_section_help("Alerts & Trends")
            low_q_threshold = st.slider(
                "Alert threshold: low-quality rate",
                min_value=0.05,
                max_value=0.60,
                value=0.25,
                step=0.01,
                help=mode_aware_tooltip(
                    "Set how quickly the app should warn you about low-quality results. Lower values warn sooner.",
                    "Alert triggers when low-quality fraction exceeds this value. Lower threshold = higher sensitivity.",
                    tooltip_power_user_mode,
                ),
            )
            alerts = compute_lab_alerts(root, max_low_quality_rate=low_q_threshold)
            if not alerts:
                st.success("No active lab alerts from latest run.")
            else:
                for alert in alerts:
                    if alert["severity"] == "high":
                        st.error(alert["message"])
                    else:
                        st.warning(alert["message"])

            trend_days = st.selectbox(
                "Trend window",
                [7, 30],
                index=1,
                help=mode_aware_tooltip(
                    "Choose how many days to include in trend charts.",
                    "Number of recent days included in trend charts.",
                    tooltip_power_user_mode,
                ),
            )
            trend_df = collect_run_trends(root, day_window=int(trend_days))
            if trend_df.empty:
                st.caption("No recent run data available for trend charts yet.")
            else:
                st.line_chart(trend_df.set_index("timestamp")[["low_quality_rate", "median_caption_quality", "spectral_drift_rate"]])
                st.bar_chart(trend_df.set_index("timestamp")[["processed_count", "failed_count", "hold_count"]])

            st.markdown("---")
            render_section_glance_image("Cell/Media Visualizations", "🧫", "#0b7285")
            st.markdown("### Cell/Media Visualizations")
            render_section_help("Cell/Media Visualizations")
            current_run = default_cellmedia_run_dir(root)
            if current_run:
                render_cell_media_visualization(current_run)
            else:
                st.caption("No run directory available yet for cell/media visualizations.")

        st.markdown("---")
        st.markdown(f"### {ui_text(use_lab_language, 'Bug Reporter')}")
        bug_report_dir = root / "bug_reports"
        with st.form("streamlined_bug_report_form"):
            bug_title = st.text_input("Bug title", placeholder="Example: Readiness step does not load latest records")
            bug_area = st.selectbox("Area", ["Daily QC", "Readiness", "ELN/LIMS Export", "Drift & Promotion", "Weekly PI Summary", "METAFlux", "General UI"])
            bug_severity = st.selectbox("Severity", ["Critical", "High", "Medium", "Low"], index=2)
            bug_repro = st.checkbox("Reproducible", value=True)
            bug_expected = st.text_area("Expected behavior", height=90)
            bug_actual = st.text_area("Actual behavior", height=90)
            bug_steps = st.text_area("Steps to reproduce (one per line)", height=120)
            bug_data = st.text_area("Related files/paths (one per line)", height=80)
            bug_notes = st.text_area("Additional context", height=80)
            submit_bug = st.form_submit_button(ui_text(use_lab_language, "Save Bug Report"), type="primary")

        if submit_bug:
            if not bug_title.strip() or not bug_actual.strip() or not bug_steps.strip():
                st.error("Please fill at least: Bug title, Actual behavior, and Steps to reproduce.")
            else:
                md_path, json_path = save_bug_report(
                    report_dir=bug_report_dir,
                    title=bug_title.strip(),
                    area=bug_area,
                    severity=bug_severity,
                    reproducible=bug_repro,
                    expected=bug_expected.strip(),
                    actual=bug_actual.strip(),
                    steps=bug_steps.strip(),
                    data_paths=bug_data.strip(),
                    notes=bug_notes.strip(),
                    python_exe=python_exe,
                    project_root=root,
                    interface_mode=mode,
                    latest_run_name=latest_run.name if latest_run else "none",
                )
                st.success("Bug report saved in AI-crawlable format.")
                st.info(f"Markdown: {md_path}")
                st.info(f"JSON: {json_path}")

        return

    render_glutamate_reminder()
    render_data_preservation_reminder()
    daily_tab, drift_tab, weekly_tab, eln_tab, readiness_tab, insights_tab, cellmedia_tab, metaflux_tab, collab_tab, bug_tab = st.tabs(
        [
            ui_text(use_lab_language, "Daily QC Run"),
            ui_text(use_lab_language, "Drift & Promotion"),
            ui_text(use_lab_language, "Weekly PI Summary"),
            ui_text(use_lab_language, "ELN/LIMS Export"),
            ui_text(use_lab_language, "Readiness"),
            "Alerts & Trends",
            "Cell/Media Viz",
            "METAFlux",
            "Collaboration",
            ui_text(use_lab_language, "Bug Reporter"),
        ]
    )

    with daily_tab:
        render_section_glance_image("Daily QC", "🔬", "#0f6b62")
        st.subheader(ui_text(use_lab_language, "Run Daily QC Pipeline"))
        render_section_help("Daily QC")
        default_cfg = root / "config.validation_ops.yaml"
        config_path = st.text_input(
            "Config file",
            value=str(default_cfg),
            key="daily_cfg",
            help=mode_aware_tooltip(
                "This file tells the app how to run. Leave it as-is unless you were told to use a different config.",
                "Pipeline configuration YAML. Change this only when intentionally selecting a different run profile.",
                tooltip_power_user_mode,
            ),
        )
        cal_enabled_custom = st.checkbox(
            "Enable spectral calibration",
            value=True,
            key="custom_cal_enabled",
            help=mode_aware_tooltip(
                "Makes images look more consistent before quality scoring.",
                "Normalizes color and illumination before QC scoring to improve consistency across instruments.",
                tooltip_power_user_mode,
            ),
        )
        cal_wb_mode_custom = st.selectbox(
            "Calibration white balance mode",
            ["grayworld", "reference_patch"],
            index=0,
            key="custom_cal_wb",
            help=mode_aware_tooltip(
                "Use grayworld for normal images. Use reference patch if your image includes a known patch.",
                "Use grayworld for general images; use reference_patch when a calibration patch is present.",
                tooltip_power_user_mode,
            ),
        )
        cal_gamma_custom = st.slider(
            "Calibration gamma",
            min_value=0.5,
            max_value=2.0,
            value=1.0,
            step=0.05,
            key="custom_cal_gamma",
            help=mode_aware_tooltip(
                "Changes middle brightness in images. Lower is darker, higher is brighter.",
                "Adjusts mid-tone response during calibration. Lower darkens mid-tones; higher brightens them.",
                tooltip_power_user_mode,
            ),
        )

        if st.button(
            ui_text(use_lab_language, "Run Daily QC"),
            type="primary",
            help=mode_aware_tooltip(
                "Start a full quality check now and view results on this page.",
                "Runs the full Daily QC pipeline in foreground and returns logs/results in-page.",
                tooltip_power_user_mode,
            ),
        ):
            runtime_cfg_path = root / "_tmp_webui_runtime_config_custom.yaml"
            runtime_cfg = write_runtime_config(
                base_config_path=Path(config_path),
                runtime_overrides={
                    "spectral_calibration": {
                        "enabled": bool(cal_enabled_custom),
                        "white_balance_mode": cal_wb_mode_custom,
                        "gamma_correction": float(cal_gamma_custom),
                    }
                },
                out_path=runtime_cfg_path,
            )
            cmd = [python_exe, str(root / "run_pipeline.py"), "--config", str(runtime_cfg)]
            result = run_command(cmd, cwd=root)
            show_command_result(ui_text(use_lab_language, "Daily QC"), result)
        if st.button(
            "Start Daily QC (BG)",
            key="custom_bg_daily",
            help=mode_aware_tooltip(
                "Run quality checks in the background while you keep working.",
                "Starts Daily QC in background while preserving interactivity.",
                tooltip_power_user_mode,
            ),
        ):
            runtime_cfg_path = root / "_tmp_webui_runtime_config_custom_bg.yaml"
            runtime_cfg = write_runtime_config(
                base_config_path=Path(config_path),
                runtime_overrides={
                    "spectral_calibration": {
                        "enabled": bool(cal_enabled_custom),
                        "white_balance_mode": cal_wb_mode_custom,
                        "gamma_correction": float(cal_gamma_custom),
                    }
                },
                out_path=runtime_cfg_path,
            )
            process_id = start_managed_process(
                name="Daily QC",
                command=[python_exe, str(root / "run_pipeline.py"), "--config", str(runtime_cfg)],
                cwd=root,
            )
            st.success(f"Background process started: {process_id}")
        if st.button(
            "Replay Failed Items",
            key="custom_replay_failed",
            help=mode_aware_tooltip(
                "Only retry items that failed before.",
                "Retries failed items from earlier runs without rerunning successful items.",
                tooltip_power_user_mode,
            ),
        ):
            replay_result = replay_failed_run(root, python_exe, Path(config_path))
            show_command_result("Replay Failed Items", replay_result)

    with drift_tab:
        st.subheader(ui_text(use_lab_language, "Drift Evaluation"))
        render_section_help("Drift Evaluation")
        baseline_csv = st.text_input(
            "Baseline records.csv",
            value=str(root / "output_caption_subset" / "records.csv"),
            key="baseline_csv",
            help=mode_aware_tooltip(
                "The older results file you trust and want to compare against.",
                "Reference records file used as approved baseline for drift comparison.",
                tooltip_power_user_mode,
            ),
        )
        candidate_csv = st.text_input(
            "Candidate records.csv",
            value=str(root / "output_caption_subset_bliplarge" / "records.csv"),
            key="candidate_csv",
            help=mode_aware_tooltip(
                "The new results file you want to test against the baseline.",
                "Candidate model/run records file to compare against baseline behavior.",
                tooltip_power_user_mode,
            ),
        )
        drift_out = st.text_input(
            "Drift output folder",
            value=str(root / "output_caption_drift_subset"),
            key="drift_out",
            help=mode_aware_tooltip(
                "Folder where drift results and reports will be saved.",
                "Directory where drift metrics and reports are written.",
                tooltip_power_user_mode,
            ),
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                ui_text(use_lab_language, "Run Drift Evaluation"),
                type="primary",
                help=mode_aware_tooltip(
                    "Compare old vs new results and measure how different they are.",
                    "Computes drift metrics between baseline and candidate records.",
                    tooltip_power_user_mode,
                ),
            ):
                cmd = [
                    python_exe,
                    str(root / "evaluate_caption_drift.py"),
                    "--baseline",
                    baseline_csv,
                    "--candidate",
                    candidate_csv,
                    "--output",
                    drift_out,
                ]
                result = run_command(cmd, cwd=root)
                show_command_result(ui_text(use_lab_language, "Drift Evaluation"), result)
            if st.button(
                "Run Drift Evaluation (BG)",
                key="custom_bg_drift",
                help=mode_aware_tooltip(
                    "Run this comparison in the background so you can keep using the app.",
                    "Starts drift evaluation in background and keeps UI responsive.",
                    tooltip_power_user_mode,
                ),
            ):
                process_id = start_managed_process(
                    name="Drift Evaluation",
                    command=[
                        python_exe,
                        str(root / "evaluate_caption_drift.py"),
                        "--baseline",
                        baseline_csv,
                        "--candidate",
                        candidate_csv,
                        "--output",
                        drift_out,
                    ],
                    cwd=root,
                )
                st.success(f"Background process started: {process_id}")

        with col2:
            promotion_out = st.text_input(
                ui_text(use_lab_language, "Promotion decision output JSON"),
                value=str(root / "model_promotion_decision.json"),
                key="promotion_out",
                help=mode_aware_tooltip(
                    "Where to save the final decision file.",
                    "Destination JSON for promotion decision details and rationale.",
                    tooltip_power_user_mode,
                ),
            )
            max_drift = st.number_input(
                ui_text(use_lab_language, "Max acceptable mean drift"),
                min_value=0.0,
                max_value=1.0,
                value=0.55,
                step=0.01,
                help=mode_aware_tooltip(
                    "Set how much difference is acceptable before rejecting the new version.",
                    "Decision threshold: candidate is rejected if mean drift exceeds this value.",
                    tooltip_power_user_mode,
                ),
            )
            if st.button(
                ui_text(use_lab_language, "Run Promotion Decision"),
                help=mode_aware_tooltip(
                    "Make a go/no-go decision for the new version based on the drift check.",
                    "Applies policy threshold to drift metrics and outputs go/no-go decision JSON.",
                    tooltip_power_user_mode,
                ),
            ):
                cmd = [
                    python_exe,
                    str(root / "evaluate_model_promotion.py"),
                    "--baseline",
                    baseline_csv,
                    "--candidate",
                    candidate_csv,
                    "--max-drift",
                    str(max_drift),
                    "--output",
                    promotion_out,
                ]
                result = run_command(cmd, cwd=root)
                show_command_result(ui_text(use_lab_language, "Run Promotion Decision"), result)

                decision_path = Path(promotion_out)
                if decision_path.exists():
                    try:
                        decision = json.loads(decision_path.read_text(encoding="utf-8"))
                        st.json(decision)
                    except Exception:
                        pass
            if st.button(
                "Run Promotion Decision (BG)",
                key="custom_bg_promo",
                help=mode_aware_tooltip(
                    "Make that decision in the background while you continue working.",
                    "Runs promotion decision in background for uninterrupted work.",
                    tooltip_power_user_mode,
                ),
            ):
                process_id = start_managed_process(
                    name="Promotion Decision",
                    command=[
                        python_exe,
                        str(root / "evaluate_model_promotion.py"),
                        "--baseline",
                        baseline_csv,
                        "--candidate",
                        candidate_csv,
                        "--max-drift",
                        str(max_drift),
                        "--output",
                        promotion_out,
                    ],
                    cwd=root,
                )
                st.success(f"Background process started: {process_id}")

    with weekly_tab:
        render_section_glance_image("Weekly + Telemetry", "📈", "#6c8f2a")
        st.subheader(ui_text(use_lab_language, "Generate Weekly PI Summary"))
        render_section_help("Weekly + Telemetry")
        runs_root = st.text_input(
            ui_text(use_lab_language, "Runs root folder"),
            value=str(root),
            key="runs_root",
            help=mode_aware_tooltip(
                "Main folder where your run folders are stored.",
                "Parent folder containing run outputs to summarize.",
                tooltip_power_user_mode,
            ),
        )
        pattern = st.text_input(
            ui_text(use_lab_language, "Run directory glob pattern"),
            value="output_*",
            key="runs_pattern",
            help=mode_aware_tooltip(
                "Rule for which run folders to include (for example, output_*).",
                "Glob pattern used to select run folders under runs root.",
                tooltip_power_user_mode,
            ),
        )
        weekly_md = st.text_input(
            ui_text(use_lab_language, "Output markdown file"),
            value=str(root / "weekly_pi_summary.md"),
            key="weekly_md",
            help=mode_aware_tooltip(
                "Where to save the weekly summary report.",
                "Output path for generated weekly summary markdown.",
                tooltip_power_user_mode,
            ),
        )
        telemetry_team_md = st.text_input(
            "Telemetry team report (.md)",
            value=str(root / "telemetry_team_report.md"),
            key="telemetry_team_md",
            help=mode_aware_tooltip(
                "Where to save a team-friendly report.",
                "Human-readable telemetry summary output path.",
                tooltip_power_user_mode,
            ),
        )
        telemetry_ai_json = st.text_input(
            "Telemetry AI report (.json)",
            value=str(root / "telemetry_ai_report.json"),
            key="telemetry_ai_json",
            help=mode_aware_tooltip(
                "Where to save a machine-friendly report for tools and automation.",
                "Machine-readable telemetry output for automation/AI workflows.",
                tooltip_power_user_mode,
            ),
        )
        telemetry_window = st.number_input(
            "Telemetry window days",
            min_value=1,
            max_value=365,
            value=30,
            step=1,
            key="telemetry_window",
            help=mode_aware_tooltip(
                "How many recent days to include in telemetry reports.",
                "Number of recent days included in telemetry calculations.",
                tooltip_power_user_mode,
            ),
        )

        if st.button(
            ui_text(use_lab_language, "Generate Weekly Summary"),
            type="primary",
            help=mode_aware_tooltip(
                "Create a weekly summary from the selected runs.",
                "Builds a weekly markdown summary across selected run outputs.",
                tooltip_power_user_mode,
            ),
        ):
            cmd = [
                python_exe,
                str(root / "generate_weekly_pi_summary.py"),
                "--runs-root",
                runs_root,
                "--pattern",
                pattern,
                "--output",
                weekly_md,
            ]
            result = run_command(cmd, cwd=root)
            show_command_result(ui_text(use_lab_language, "Weekly PI Summary"), result)

            out_path = Path(weekly_md)
            if out_path.exists():
                st.markdown("### Summary Preview")
                st.markdown(out_path.read_text(encoding="utf-8"))

        if st.button(
            "Export Telemetry (Team + AI)",
            key="custom_export_telemetry",
            type="secondary",
            help=mode_aware_tooltip(
                "Create reports for both people and automation tools.",
                "Generates both human-readable (.md) and machine-readable (.json) telemetry reports.",
                tooltip_power_user_mode,
            ),
        ):
            cmd = [
                python_exe,
                str(root / "export_telemetry_reports.py"),
                "--runs-root",
                runs_root,
                "--team-output",
                telemetry_team_md,
                "--ai-output",
                telemetry_ai_json,
                "--pattern",
                pattern,
                "--window-days",
                str(int(telemetry_window)),
            ]
            result = run_command(cmd, cwd=root)
            show_command_result("Telemetry Export", result)
            if result.get("ok"):
                st.info(f"Team report: {telemetry_team_md}")
                st.info(f"AI report: {telemetry_ai_json}")
        if st.button(
            "Export Telemetry (BG)",
            key="custom_bg_telemetry",
            help=mode_aware_tooltip(
                "Export telemetry in the background while you keep working.",
                "Starts telemetry export in background while you continue using the app.",
                tooltip_power_user_mode,
            ),
        ):
            process_id = start_managed_process(
                name="Telemetry Export",
                command=[
                    python_exe,
                    str(root / "export_telemetry_reports.py"),
                    "--runs-root",
                    runs_root,
                    "--team-output",
                    telemetry_team_md,
                    "--ai-output",
                    telemetry_ai_json,
                    "--pattern",
                    pattern,
                    "--window-days",
                    str(int(telemetry_window)),
                ],
                cwd=root,
            )
            st.success(f"Background process started: {process_id}")

        st.markdown("#### METAFlux Analyzer")
        custom_metaflux_cfg = st.text_input(
            "METAFlux config (.json)",
            value=str(root / "metaflux_config.example.json"),
            key="custom_metaflux_cfg",
            help=mode_aware_tooltip(
                "Settings file for the METAFlux run.",
                "Config JSON controlling METAFlux inputs, parameters, and output paths.",
                tooltip_power_user_mode,
            ),
        )
        cmeta1, cmeta2 = st.columns(2)
        with cmeta1:
            if st.button(
                "Run METAFlux Analyzer",
                key="custom_run_metaflux",
                type="secondary",
                help=mode_aware_tooltip(
                    "Run the METAFlux analysis using your selected settings.",
                    "Runs metabolic flux analysis from configured expression inputs.",
                    tooltip_power_user_mode,
                ),
            ):
                result = run_metaflux_from_webapp(root, rscript_exe, Path(custom_metaflux_cfg))
                show_command_result("METAFlux Analyzer", result)
                if result.get("ok"):
                    st.success("METAFlux run completed. Check output_dir from config.")
        with cmeta2:
            if st.button(
                "Run METAFlux Analyzer (BG)",
                key="custom_bg_metaflux",
                help=mode_aware_tooltip(
                    "Run METAFlux in the background for longer jobs.",
                    "Starts METAFlux in background for longer runs.",
                    tooltip_power_user_mode,
                ),
            ):
                launcher = root / "run_metaflux_analyzer.R"
                cfg_path = Path(custom_metaflux_cfg)
                if not launcher.exists():
                    st.error(f"METAFlux launcher not found: {launcher}")
                elif not cfg_path.exists():
                    st.error(f"METAFlux config not found: {cfg_path}")
                else:
                    process_id = start_managed_process(
                        name="METAFlux Analyzer",
                        command=[rscript_exe, str(launcher), "--config", str(cfg_path)],
                        cwd=root,
                    )
                    st.success(f"Background process started: {process_id}")

    with eln_tab:
        render_section_glance_image("ELN/LIMS Export", "📦", "#7b4ea3")
        st.subheader(ui_text(use_lab_language, "Export ELN/LIMS Package"))
        render_section_help("ELN/LIMS Export")
        default_eln_run_dir = default_cellmedia_run_dir(root) or (root / "output_caption_microscopy_full_bliplarge")
        run_dir = st.text_input(
            ui_text(use_lab_language, "Run output folder"),
            value=str(default_eln_run_dir),
            key="eln_run_dir",
            help=mode_aware_tooltip(
                "Choose which run folder to package.",
                "Run directory to package for ELN/LIMS handoff.",
                tooltip_power_user_mode,
            ),
        )
        out_dir = st.text_input(
            ui_text(use_lab_language, "Package destination folder"),
            value=str(root / "eln_packages"),
            key="eln_out_dir",
            help=mode_aware_tooltip(
                "Folder where the package files will be saved.",
                "Destination folder for generated package artifacts.",
                tooltip_power_user_mode,
            ),
        )
        export_ready_custom = render_qc_checklist_gate("custom_export")

        if st.button(
            ui_text(use_lab_language, "Export ELN/LIMS Package"),
            type="primary",
            disabled=not export_ready_custom,
            help=mode_aware_tooltip(
                "Create a package from this run that is ready to hand off.",
                "Creates handoff-ready ELN/LIMS package from the selected run folder.",
                tooltip_power_user_mode,
            ),
        ):
            cmd = [
                python_exe,
                str(root / "export_eln_lims_package.py"),
                "--run-dir",
                run_dir,
                "--out-dir",
                out_dir,
            ]
            result = run_command(cmd, cwd=root)
            show_command_result(ui_text(use_lab_language, "ELN/LIMS Export"), result)
        if st.button(
            "Export ELN/LIMS Package (BG)",
            key="custom_bg_eln",
            disabled=not export_ready_custom,
            help=mode_aware_tooltip(
                "Build that package in the background so you can keep working.",
                "Starts ELN/LIMS export in background for larger package jobs.",
                tooltip_power_user_mode,
            ),
        ):
            process_id = start_managed_process(
                name="ELN/LIMS Export",
                command=[
                    python_exe,
                    str(root / "export_eln_lims_package.py"),
                    "--run-dir",
                    run_dir,
                    "--out-dir",
                    out_dir,
                ],
                cwd=root,
            )
            st.success(f"Background process started: {process_id}")
        if st.button(
            "Create Run Fingerprint",
            key="custom_create_fingerprint",
            help=mode_aware_tooltip(
                "Save a fingerprint file so this run can be traced and checked later.",
                "Builds reproducibility metadata with hashes, environment details, and git state.",
                tooltip_power_user_mode,
            ),
        ):
            target_run = Path(run_dir)
            if not target_run.exists():
                st.warning(f"Run folder not found: {target_run}")
            else:
                fp = create_run_fingerprint(target_run, Path(root / "config.validation_ops.yaml"), python_exe, root)
                st.success(f"Run fingerprint saved: {fp}")

    with readiness_tab:
        render_section_glance_image("Readiness", "📊", "#3d6fb6")
        st.subheader(ui_text(use_lab_language, "Sample Readiness Triage"))
        render_section_help("Readiness")
        default_records = (latest_run / "records.csv") if latest_run else (root / "output_caption_microscopy_full_bliplarge" / "records.csv")
        records_csv = st.text_input(
            ui_text(use_lab_language, "records.csv path"),
            value=str(default_records),
            key="readiness_csv",
            help=mode_aware_tooltip(
                "Path to the results file used for readiness sorting.",
                "Path to records.csv used for readiness classification.",
                tooltip_power_user_mode,
            ),
        )

        if st.button(
            ui_text(use_lab_language, "Compute Readiness"),
            type="primary",
            help=mode_aware_tooltip(
                "Sort results into ready, review, or hold and explain why.",
                "Generates readiness triage with reasons for ready/review/hold decisions.",
                tooltip_power_user_mode,
            ),
        ):
            readiness_preview(Path(records_csv))

    with insights_tab:
        render_section_glance_image("Alerts & Trends", "🚨", "#b15a00")
        st.subheader("Alerts & Trends")
        render_section_help("Alerts & Trends")
        low_q_threshold = st.slider(
            "Alert threshold: low-quality rate",
            min_value=0.05,
            max_value=0.60,
            value=0.25,
            step=0.01,
            key="custom_low_q",
            help=mode_aware_tooltip(
                "Set when low-quality warnings should appear. Lower means earlier warnings.",
                "Alert triggers when low-quality ratio exceeds this threshold.",
                tooltip_power_user_mode,
            ),
        )
        alerts = compute_lab_alerts(root, max_low_quality_rate=low_q_threshold)
        if not alerts:
            st.success("No active lab alerts from latest run.")
        else:
            for alert in alerts:
                if alert["severity"] == "high":
                    st.error(alert["message"])
                else:
                    st.warning(alert["message"])

        trend_days = st.selectbox(
            "Trend window",
            [7, 30],
            index=1,
            key="custom_trend_days",
            help=mode_aware_tooltip(
                "Choose how many days to show in trend charts.",
                "Number of recent days included in trend charts.",
                tooltip_power_user_mode,
            ),
        )
        trend_df = collect_run_trends(root, day_window=int(trend_days))
        if trend_df.empty:
            st.caption("No recent run data available for trend charts yet.")
        else:
            st.line_chart(trend_df.set_index("timestamp")[["low_quality_rate", "median_caption_quality", "spectral_drift_rate"]])
            st.bar_chart(trend_df.set_index("timestamp")[["processed_count", "failed_count", "hold_count"]])

    with cellmedia_tab:
        render_section_glance_image("Cell/Media Visualizations", "🧫", "#0b7285")
        st.subheader("Cell/Media Visualizations")
        render_section_help("Cell/Media Visualizations")
        run_options = run_output_dirs(root)
        if not run_options:
            st.caption("No run folders available yet.")
        else:
            run_names = [p.name for p in run_options]
            default_index = run_names.index(PREFERRED_CELLMEDIA_RUN) if PREFERRED_CELLMEDIA_RUN in run_names else 0
            selected_run_name = st.selectbox(
                "Run folder",
                run_names,
                index=default_index,
                key="cellmedia_run_select",
                help=mode_aware_tooltip(
                    "Pick which run to open in the cell/media charts.",
                    "Select run directory for cell/media charts and heatmap rendering.",
                    tooltip_power_user_mode,
                ),
            )
            selected_run = next((p for p in run_options if p.name == selected_run_name), run_options[0])
            render_cell_media_visualization(selected_run)

    with metaflux_tab:
        render_section_glance_image("METAFlux", "🧬", "#2d5a27")
        st.subheader("METAFlux Pathway & Nutrient Flux Analysis")
        render_section_help("METAFlux")
        docs = Path.home() / "Documents"
        default_metaflux_cfg = root / "metaflux_config.example.yaml"
        if not default_metaflux_cfg.exists():
            default_metaflux_cfg = docs / "metaflux_config.example.yaml"
        default_metaflux_r = root / "metaflux_pipeline_refactored.R"
        if not default_metaflux_r.exists():
            default_metaflux_r = docs / "metaflux_pipeline_refactored.R"
        rscript_exe = st.text_input("Rscript executable", value=default_rscript_exe(), key="metaflux_rscript")
        config_path_meta = st.text_input("Config YAML path", value=str(default_metaflux_cfg), key="metaflux_cfg")
        config_upload = st.file_uploader("Or upload config YAML", type=["yaml", "yml"], key="metaflux_cfg_upload")
        cfg_path_for_assumptions = Path(config_path_meta)
        if cfg_path_for_assumptions.exists():
            try:
                _acfg = yaml.safe_load(cfg_path_for_assumptions.read_text(encoding="utf-8"))
                with st.expander("Assumptions (from config)"):
                    paths = _acfg.get("paths", {})
                    model = _acfg.get("model", {})
                    st.write("**Paths:**", paths.get("project_root", "—"), "| RNA-seq:", paths.get("rnaseq_file", "—"))
                    st.write("**Knockout genes:**", model.get("knockout_genes", []))
                    st.write("**Nutrients to plot:**", model.get("nutrients_to_plot", []))
                    st.write("**Medium profile:**", model.get("medium_profile_name", "cell_medium"))
            except Exception:
                pass
        rnaseq_upload = st.file_uploader("Or upload RNA-seq file (Excel)", type=["xlsx", "xls"], key="metaflux_rnaseq_upload")
        rscript_path = st.text_input("METAFlux R script path", value=str(default_metaflux_r), key="metaflux_r_script")
        if st.button("Run METAFlux", type="primary", key="metaflux_run"):
            if config_upload:
                tmp_cfg = root / "_tmp_metaflux_webui_config.yaml"
                tmp_cfg.write_bytes(config_upload.getvalue())
                cfg_path = tmp_cfg
            else:
                cfg_path = Path(config_path_meta)
            rnaseq_override = None
            if rnaseq_upload:
                rnaseq_tmp = root / "_tmp_metaflux_webui_rnaseq"
                rnaseq_tmp.mkdir(parents=True, exist_ok=True)
                rnaseq_path = rnaseq_tmp / (rnaseq_upload.name or "uploaded_rnaseq.xlsx")
                rnaseq_path.write_bytes(rnaseq_upload.getvalue())
                rnaseq_override = rnaseq_path
            result, out_dir = run_metaflux_refactored(root, rscript_exe, cfg_path, rnaseq_override)
            show_command_result("METAFlux", result)
            if result.get("ok") and out_dir and out_dir.exists():
                st.success(f"Outputs: {out_dir}")
                render_metaflux_results(out_dir)
        if st.button("Run METAFlux (BG)", key="metaflux_run_bg", help="Run METAFlux in background for longer jobs."):
            if config_upload:
                tmp_cfg = root / "_tmp_metaflux_webui_config.yaml"
                tmp_cfg.write_bytes(config_upload.getvalue())
                cfg_path = tmp_cfg
            else:
                cfg_path = Path(config_path_meta)
            rnaseq_override = None
            if rnaseq_upload:
                rnaseq_tmp = root / "_tmp_metaflux_webui_rnaseq"
                rnaseq_tmp.mkdir(parents=True, exist_ok=True)
                rnaseq_path = rnaseq_tmp / (rnaseq_upload.name or "uploaded_rnaseq.xlsx")
                rnaseq_path.write_bytes(rnaseq_upload.getvalue())
                rnaseq_override = rnaseq_path
            prep = _prepare_metaflux_refactored(root, rscript_exe, cfg_path, rnaseq_override)
            if prep:
                cmd, cwd, out_dir = prep
                process_id = start_managed_process(name="METAFlux", command=cmd, cwd=cwd)
                st.success(f"METAFlux running in background. Outputs will be in: {out_dir}")
            else:
                st.error("Could not prepare METAFlux run. Check config and script paths.")
        browse_out = st.text_input("Or browse output folder", key="metaflux_browse", placeholder="e.g. C:/Users/.../runs/20250213_123456")
        if browse_out and Path(browse_out).exists():
            render_metaflux_results(Path(browse_out))

    with collab_tab:
        render_section_glance_image("Collaboration", "🤝", "#355070")
        render_collaboration_panel(
            root=root,
            current_user=collab_user,
            api_base_url=local_api_url,
            use_local_api=use_local_api,
            default_area="lab-ops",
        )

    with bug_tab:
        render_section_glance_image("Bug Reporter", "🐞", "#9b1b30")
        st.subheader(ui_text(use_lab_language, "Bug Reporter"))
        st.caption("Creates both Markdown and JSON reports so AI and humans can triage quickly.")
        bug_report_dir = root / "bug_reports"
        with st.form("custom_bug_report_form"):
            bug_title = st.text_input("Bug title", placeholder="Example: Drift report fails after benchmark run")
            bug_area = st.selectbox("Area", ["Daily QC", "Readiness", "ELN/LIMS Export", "Drift & Promotion", "Weekly PI Summary", "METAFlux", "General UI"], key="bug_area_custom")
            bug_severity = st.selectbox("Severity", ["Critical", "High", "Medium", "Low"], index=2, key="bug_severity_custom")
            bug_repro = st.checkbox("Reproducible", value=True, key="bug_repro_custom")
            bug_expected = st.text_area("Expected behavior", height=90, key="bug_expected_custom")
            bug_actual = st.text_area("Actual behavior", height=90, key="bug_actual_custom")
            bug_steps = st.text_area("Steps to reproduce (one per line)", height=120, key="bug_steps_custom")
            bug_data = st.text_area("Related files/paths (one per line)", height=80, key="bug_data_custom")
            bug_notes = st.text_area("Additional context", height=80, key="bug_notes_custom")
            submit_bug_custom = st.form_submit_button(ui_text(use_lab_language, "Save Bug Report"), type="primary")

        if submit_bug_custom:
            if not bug_title.strip() or not bug_actual.strip() or not bug_steps.strip():
                st.error("Please fill at least: Bug title, Actual behavior, and Steps to reproduce.")
            else:
                md_path, json_path = save_bug_report(
                    report_dir=bug_report_dir,
                    title=bug_title.strip(),
                    area=bug_area,
                    severity=bug_severity,
                    reproducible=bug_repro,
                    expected=bug_expected.strip(),
                    actual=bug_actual.strip(),
                    steps=bug_steps.strip(),
                    data_paths=bug_data.strip(),
                    notes=bug_notes.strip(),
                    python_exe=python_exe,
                    project_root=root,
                    interface_mode=mode,
                    latest_run_name=latest_run.name if latest_run else "none",
                )
                st.success("Bug report saved in AI-crawlable format.")
                st.info(f"Markdown: {md_path}")
                st.info(f"JSON: {json_path}")

    # Process monitor already rendered near the top for always-visible shift operations.


if __name__ == "__main__":
    main()
