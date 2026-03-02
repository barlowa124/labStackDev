from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from python_compat import require_supported_python


def main() -> int:
    supported, compat_msg = require_supported_python()
    if not supported:
        print(compat_msg)
        return 2

    parser = argparse.ArgumentParser(description="Create ELN/LIMS package from a run output folder")
    parser.add_argument("--run-dir", required=True, help="Run output directory")
    parser.add_argument("--out-dir", required=True, help="Destination directory for package")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pkg_dir = out_dir / f"eln_lims_package_{stamp}"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    files = [
        "records.csv",
        "records.jsonl",
        "low_quality_records.csv",
        "run_metadata.json",
        "run_status.json",
        "run_manifest_signed.json",
        "condition_summary.csv",
        "batch_effects.json",
        "sanity_warnings.json",
        "report.md",
    ]

    included = []
    for name in files:
        src = run_dir / name
        if src.exists():
            shutil.copy2(src, pkg_dir / name)
            included.append(name)

    manifest = {
        "source_run_dir": str(run_dir),
        "packaged_at": datetime.utcnow().isoformat() + "Z",
        "included_files": included,
    }
    (pkg_dir / "package_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    zip_base = str(pkg_dir)
    zip_path = shutil.make_archive(zip_base, "zip", root_dir=pkg_dir)

    print(json.dumps({"status": "ok", "package_dir": str(pkg_dir), "zip": zip_path, "included": included}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
