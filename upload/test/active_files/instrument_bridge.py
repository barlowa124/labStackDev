from __future__ import annotations

import argparse
import io
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from io_utils import list_images
from pipeline import run_pipeline
from python_compat import require_supported_python


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _default_bridge_config(root: Path) -> dict[str, Any]:
    return {
        "enabled": True,
        "poll_seconds": 30,
        "recursive": True,
        "min_new_images": 1,
        "state_file": str(root / ".instrument_bridge_state.json"),
        "staging_root": str(root / "instrument_ingest"),
        "sources": [],
    }


def _default_google_workspace_config(root: Path) -> dict[str, Any]:
    return {
        "enabled": False,
        "credentials_file": str(Path.home() / "Documents" / "credentials.json"),
        "token_file": str(Path.home() / "Documents" / "token.json"),
        "oauth_host": "127.0.0.1",
        "oauth_port": 8765,
        "scopes": [
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        "drive_folder_id": "",
        "drive_mirror_dir": str(root / "google_drive_ingest"),
        "drive_page_size": 100,
    }


def _merge_bridge_config(cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    merged = _default_bridge_config(root)
    user_cfg = cfg.get("instrument_bridge", {}) if isinstance(cfg, dict) else {}
    if isinstance(user_cfg, dict):
        merged.update(user_cfg)
    return merged


def _merge_google_workspace_config(cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    merged = _default_google_workspace_config(root)
    user_cfg = cfg.get("google_workspace", {}) if isinstance(cfg, dict) else {}
    if isinstance(user_cfg, dict):
        merged.update(user_cfg)
    return merged


def _get_google_credentials(workspace_cfg: dict[str, Any]):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except Exception as exc:
        print(f"Google client libraries not available: {exc}")
        print("Install: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
        return None

    scopes = workspace_cfg.get("scopes", [])
    token_file = Path(str(workspace_cfg.get("token_file", ""))).expanduser()
    credentials_file = Path(str(workspace_cfg.get("credentials_file", ""))).expanduser()

    creds = None
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), scopes=scopes)
        except Exception:
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_file.write_text(creds.to_json(), encoding="utf-8")
        except Exception:
            creds = None

    if not creds:
        if not credentials_file.exists():
            print(f"Google credentials file not found: {credentials_file}")
            return None
        try:
            oauth_host = str(workspace_cfg.get("oauth_host", "127.0.0.1")).strip() or "127.0.0.1"
            oauth_port = int(workspace_cfg.get("oauth_port", 8765))
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes=scopes)
            creds = flow.run_local_server(
                host=oauth_host,
                port=oauth_port,
                open_browser=True,
                authorization_prompt_message=(
                    "Open this URL in your browser and complete consent:\n{url}"
                ),
                success_message="Authorization received. You can close this tab.",
            )
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(creds.to_json(), encoding="utf-8")
        except Exception as exc:
            print(f"Failed Google OAuth flow: {exc}")
            return None

    return creds


def _sync_google_drive_folder(workspace_cfg: dict[str, Any], state: dict[str, Any], extensions: list[str]) -> list[Path]:
    if not bool(workspace_cfg.get("enabled", False)):
        return []

    folder_id = str(workspace_cfg.get("drive_folder_id", "")).strip()
    if not folder_id:
        return []

    creds = _get_google_credentials(workspace_cfg)
    if creds is None:
        return []

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
    except Exception as exc:
        print(f"Google API client not available: {exc}")
        return []

    mirror_dir = Path(str(workspace_cfg.get("drive_mirror_dir", ""))).expanduser()
    mirror_dir.mkdir(parents=True, exist_ok=True)
    page_size = max(10, int(workspace_cfg.get("drive_page_size", 100)))
    allowed_ext = {e.lower() for e in extensions}

    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    state_key = "google_drive_known_files"
    known = state.get(state_key, {}) if isinstance(state.get(state_key), dict) else {}
    downloaded: list[Path] = []

    query = f"'{folder_id}' in parents and trashed=false"
    page_token = None
    while True:
        response = service.files().list(
            q=query,
            spaces="drive",
            fields="nextPageToken, files(id, name, modifiedTime, mimeType)",
            pageSize=page_size,
            pageToken=page_token,
        ).execute()

        for item in response.get("files", []):
            name = str(item.get("name", ""))
            mime_type = str(item.get("mimeType", ""))
            if mime_type.startswith("application/vnd.google-apps"):
                continue
            suffix = Path(name).suffix.lower()
            if suffix and suffix not in allowed_ext:
                continue

            file_id = str(item.get("id", ""))
            modified = str(item.get("modifiedTime", ""))
            signature = f"{modified}:{name}"
            if known.get(file_id) == signature:
                continue

            dest = mirror_dir / name
            if dest.exists():
                stem = dest.stem
                dest = mirror_dir / f"{stem}_{int(time.time())}{dest.suffix}"

            request = service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            dest.write_bytes(buffer.getvalue())
            known[file_id] = signature
            downloaded.append(dest)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    state[state_key] = known
    if downloaded:
        state["google_drive_last_sync_local"] = datetime.now().isoformat(timespec="seconds")
    return downloaded


def _discover_new_images(
    source_dirs: list[Path],
    recursive: bool,
    extensions: list[str],
    state: dict[str, Any],
) -> list[Path]:
    known = state.get("known_files", {}) if isinstance(state.get("known_files"), dict) else {}
    fresh: list[Path] = []

    for source_dir in source_dirs:
        if not source_dir.exists() or not source_dir.is_dir():
            continue
        for image_path in list_images(source_dir, recursive=recursive, extensions=extensions):
            key = str(image_path.resolve())
            mtime = image_path.stat().st_mtime
            signature = f"{mtime:.6f}:{image_path.stat().st_size}"
            if known.get(key) == signature:
                continue
            known[key] = signature
            fresh.append(image_path)

    state["known_files"] = known
    state["last_scan_local"] = datetime.now().isoformat(timespec="seconds")
    return fresh


def _build_batch_config(
    base_cfg: dict[str, Any],
    batch_image_dir: Path,
    output_root: Path,
    bridge_cfg: dict[str, Any],
) -> Path:
    cfg = json.loads(json.dumps(base_cfg))
    cfg.setdefault("input", {})
    cfg.setdefault("output", {})
    cfg.setdefault("runtime", {})

    cfg["input"]["image_dir"] = str(batch_image_dir)
    cfg["input"]["pptx_path"] = ""
    cfg["input"]["recursive"] = False
    cfg["output"]["root_dir"] = str(output_root)
    cfg["runtime"]["resume_enabled"] = False

    out_cfg = batch_image_dir.parent / "bridge_runtime_config.yaml"
    out_cfg.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return out_cfg


def _copy_batch(images: list[Path], staging_dir: Path) -> list[Path]:
    staging_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for src in images:
        dst = staging_dir / src.name
        if dst.exists():
            stem = src.stem
            suffix = src.suffix
            dst = staging_dir / f"{stem}_{int(src.stat().st_mtime)}{suffix}"
        shutil.copy2(src, dst)
        copied.append(dst)
    return copied


def run_bridge(config_path: Path, once: bool = False) -> int:
    supported, compat_msg = require_supported_python()
    if not supported:
        print(compat_msg)
        return 2

    cfg = _load_yaml(config_path)
    project_root = config_path.parent.resolve()
    bridge_cfg = _merge_bridge_config(cfg, project_root)
    workspace_cfg = _merge_google_workspace_config(cfg, project_root)
    if not bool(bridge_cfg.get("enabled", True)):
        print("instrument_bridge is disabled in config.")
        return 0

    source_dirs = [Path(p).expanduser() for p in bridge_cfg.get("sources", []) if str(p).strip()]
    if bool(workspace_cfg.get("enabled", False)):
        mirror = Path(str(workspace_cfg.get("drive_mirror_dir", project_root / "google_drive_ingest"))).expanduser()
        source_dirs.append(mirror)
    if not source_dirs:
        print("No instrument_bridge.sources configured. Nothing to watch.")
        return 0

    extensions = cfg.get("input", {}).get("image_extensions", [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"])
    recursive = bool(bridge_cfg.get("recursive", True))
    poll_seconds = max(5, int(bridge_cfg.get("poll_seconds", 30)))
    min_new_images = max(1, int(bridge_cfg.get("min_new_images", 1)))

    state_path = Path(str(bridge_cfg.get("state_file", project_root / ".instrument_bridge_state.json"))).expanduser()
    staging_root = Path(str(bridge_cfg.get("staging_root", project_root / "instrument_ingest"))).expanduser()
    state = _load_json(state_path)

    print("Instrument bridge started.")
    print(json.dumps({
        "sources": [str(p) for p in source_dirs],
        "poll_seconds": poll_seconds,
        "min_new_images": min_new_images,
        "state_file": str(state_path),
        "staging_root": str(staging_root),
    }, indent=2))

    while True:
        pulled = _sync_google_drive_folder(workspace_cfg, state=state, extensions=extensions)
        if pulled:
            print(f"Pulled {len(pulled)} new file(s) from Google Drive mirror.")
        fresh = _discover_new_images(source_dirs, recursive=recursive, extensions=extensions, state=state)
        _save_json(state_path, state)

        if len(fresh) >= min_new_images:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            batch_dir = staging_root / f"batch_{stamp}" / "images"
            copied = _copy_batch(fresh, batch_dir)

            output_root = Path(cfg.get("output", {}).get("root_dir", str(project_root / "output_bridge"))).expanduser()
            output_batch = output_root.parent / f"{output_root.name}_bridge_{stamp}"
            batch_cfg_path = _build_batch_config(cfg, batch_dir, output_batch, bridge_cfg)

            print(f"Detected {len(copied)} new images. Running pipeline for batch {stamp}...")
            result = run_pipeline(batch_cfg_path)
            print(json.dumps({
                "status": "ok",
                "batch": stamp,
                "processed_count": result.processed_count,
                "output_root": str(result.output_root),
            }, indent=2))

            state["last_run_local"] = datetime.now().isoformat(timespec="seconds")
            state["last_batch_output"] = str(result.output_root)
            _save_json(state_path, state)
        else:
            print(f"No new instrument images (found {len(fresh)} new).")

        if once:
            return 0
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-monitor instrument export folders and trigger QC pipeline.")
    parser.add_argument("--config", required=True, help="Path to YAML pipeline config")
    parser.add_argument("--once", action="store_true", help="Run one scan cycle then exit")
    args = parser.parse_args()

    cfg = Path(args.config).expanduser().resolve()
    if not cfg.exists():
        print(f"Config not found: {cfg}")
        return 2
    return run_bridge(cfg, once=bool(args.once))


if __name__ == "__main__":
    raise SystemExit(main())
