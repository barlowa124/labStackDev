from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline import run_pipeline
from python_compat import require_supported_python


def main() -> int:
    supported, compat_msg = require_supported_python()
    if not supported:
        print(compat_msg)
        return 2

    parser = argparse.ArgumentParser(description="Cell image -> AI-accessible text pipeline")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    args = parser.parse_args()

    cfg_path = Path(args.config).expanduser()
    if not cfg_path.exists():
        print(f"Config not found: {cfg_path}")
        return 2

    result = run_pipeline(cfg_path)
    print(json.dumps({
        "status": "ok",
        "processed_count": result.processed_count,
        "output_root": str(result.output_root),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
