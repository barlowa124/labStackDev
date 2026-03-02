from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


class AnalyzerTelemetry:
    def __init__(self, output_root: Path, component: str = "pipeline-analyzer") -> None:
        self.output_root = output_root
        self.component = component
        self._events: list[dict[str, Any]] = []

    def log(self, event_type: str, **data: Any) -> None:
        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "component": self.component,
            "event_type": event_type,
            "data": data,
        }
        self._events.append(event)

    def write_files(self) -> tuple[Path, Path]:
        self.output_root.mkdir(parents=True, exist_ok=True)
        jsonl_path = self.output_root / "analyzer_telemetry.jsonl"
        summary_path = self.output_root / "analyzer_telemetry_summary.json"

        with jsonl_path.open("w", encoding="utf-8") as fh:
            for event in self._events:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")

        counts = Counter(event["event_type"] for event in self._events)
        summary = {
            "component": self.component,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "event_count": len(self._events),
            "event_type_counts": dict(counts),
            "error_events": counts.get("record_failed", 0) + counts.get("pipeline_failed", 0),
            "files": {
                "events_jsonl": str(jsonl_path),
                "summary_json": str(summary_path),
            },
        }
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return jsonl_path, summary_path


def export_telemetry_reports(
    runs_root: Path,
    team_output_md: Path,
    ai_output_json: Path,
    pattern: str = "output_*",
    day_window: int = 30,
) -> dict[str, Any]:
    runs_root = runs_root.expanduser().resolve()
    team_output_md = team_output_md.expanduser().resolve()
    ai_output_json = ai_output_json.expanduser().resolve()

    cutoff = datetime.now(timezone.utc).timestamp() - (day_window * 24 * 3600)
    run_dirs = [p for p in runs_root.glob(pattern) if p.is_dir() and p.stat().st_mtime >= cutoff]
    run_dirs = sorted(run_dirs, key=lambda p: p.stat().st_mtime, reverse=True)

    runs: list[dict[str, Any]] = []
    aggregate_counts: Counter[str] = Counter()
    total_events = 0
    total_errors = 0

    for run_dir in run_dirs:
        summary_path = run_dir / "analyzer_telemetry_summary.json"
        events_path = run_dir / "analyzer_telemetry.jsonl"
        meta_path = run_dir / "run_metadata.json"
        status_path = run_dir / "run_status.json"

        telemetry_summary = _load_json(summary_path)
        run_meta = _load_json(meta_path) or {}
        run_status = _load_json(status_path) or {}
        if not telemetry_summary:
            continue

        event_type_counts = telemetry_summary.get("event_type_counts", {})
        if isinstance(event_type_counts, dict):
            aggregate_counts.update({str(k): int(v) for k, v in event_type_counts.items()})

        event_count = int(telemetry_summary.get("event_count", 0))
        error_events = int(telemetry_summary.get("error_events", 0))
        total_events += event_count
        total_errors += error_events

        runs.append(
            {
                "run_dir": str(run_dir),
                "generated_at_utc": telemetry_summary.get("generated_at_utc"),
                "event_count": event_count,
                "error_events": error_events,
                "event_type_counts": event_type_counts,
                "run_status_light": run_status.get("run_status_light"),
                "processed_count": run_meta.get("processed_count"),
                "failed_count": run_meta.get("failed_count"),
                "selected_model_id": run_meta.get("selected_model_id"),
                "selected_device": run_meta.get("selected_device"),
                "telemetry_events_path": str(events_path) if events_path.exists() else None,
                "telemetry_summary_path": str(summary_path),
            }
        )

    ai_payload = {
        "schema_version": "1.0",
        "report_type": "analyzer-telemetry-ai-crawlable",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "window_days": day_window,
        "runs_root": str(runs_root),
        "run_count": len(runs),
        "total_event_count": total_events,
        "total_error_events": total_errors,
        "aggregate_event_type_counts": dict(aggregate_counts),
        "runs": runs,
    }

    ai_output_json.parent.mkdir(parents=True, exist_ok=True)
    ai_output_json.write_text(json.dumps(ai_payload, indent=2), encoding="utf-8")

    lines = [
        "# Team Telemetry Report",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Window: last {day_window} days",
        f"- Runs included: {len(runs)}",
        f"- Total telemetry events: {total_events}",
        f"- Total telemetry error events: {total_errors}",
        "",
        "## Aggregate Event Types",
        "",
    ]

    if aggregate_counts:
        for event_name, count in sorted(aggregate_counts.items()):
            lines.append(f"- {event_name}: {count}")
    else:
        lines.append("- No telemetry events found in selected window.")

    lines.extend(["", "## Per-Run Snapshot", ""])
    for run in runs:
        lines.append(
            f"- {run['run_dir']} | status={run.get('run_status_light')} | "
            f"events={run.get('event_count')} | errors={run.get('error_events')} | "
            f"processed={run.get('processed_count')} | failed={run.get('failed_count')} | "
            f"model={run.get('selected_model_id')}"
        )

    team_output_md.parent.mkdir(parents=True, exist_ok=True)
    team_output_md.write_text("\n".join(lines), encoding="utf-8")

    return {
        "status": "ok",
        "window_days": day_window,
        "run_count": len(runs),
        "team_output_md": str(team_output_md),
        "ai_output_json": str(ai_output_json),
    }
