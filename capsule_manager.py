# -*- coding: utf-8 -*-
"""
Time Capsule Manager
Author: Anton Semenenko

Purpose:
    Externalized memory/state continuity for long-running AI/system projects.

What it does:
    - saves a timestamped state capsule as JSON
    - updates latest.json
    - updates index.json
    - optionally creates a git commit
    - can print/load the latest capsule

Usage examples:
    python capsule_manager.py save --title "PoR API stable"
    python capsule_manager.py save --title "OpenAI generate integration" --slug openai_generate --git
    python capsule_manager.py latest
    python capsule_manager.py list --limit 10

Recommended repo layout:
    repo/
      capsules/
      latest.json
      index.json
      capsule_manager.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parent
CAPSULES_DIR = ROOT / "capsules"
LATEST_FILE = ROOT / "latest.json"
INDEX_FILE = ROOT / "index.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def local_now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def ensure_dirs() -> None:
    CAPSULES_DIR.mkdir(parents=True, exist_ok=True)


def slugify(text: str, max_len: int = 64) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "_", text, flags=re.UNICODE).strip("_")
    if not text:
        text = "capsule"
    return text[:max_len]


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_git(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def is_git_repo() -> bool:
    result = run_git(["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_commit(files: List[Path], message: str) -> None:
    add_args = ["add", *[str(f.relative_to(ROOT)) for f in files]]
    add_res = run_git(add_args)
    if add_res.returncode != 0:
        raise RuntimeError(f"git add failed:\n{add_res.stderr}")

    # commit may fail if nothing changed; handle gracefully
    commit_res = run_git(["commit", "-m", message])
    if commit_res.returncode != 0:
        stderr = commit_res.stderr.strip()
        stdout = commit_res.stdout.strip()
        combined = "\n".join([p for p in [stdout, stderr] if p])
        if "nothing to commit" in combined.lower():
            print("Git: nothing to commit.")
            return
        raise RuntimeError(f"git commit failed:\n{combined}")


@dataclass
class CapsuleMeta:
    timestamp_utc: str
    timestamp_local: str
    title: str
    slug: str
    project: str
    capsule_type: str
    version: str
    tags: List[str]


@dataclass
class Capsule:
    meta: CapsuleMeta
    state: Dict[str, Any]
    boot_prompt: str
    notes: Optional[str] = None


def default_capsule_state(title: str) -> Dict[str, Any]:
    """
    Base structure. Replace/fill this with your real runtime/project state.
    """
    return {
        "project_cluster": [
            "silence-as-control",
            "PoR Kernel v0.2.0",
            "Proof-of-Resonance / PoR",
        ],
        "session_focus": title,
        "current_best_understanding": {
            "label": "early-stage control middleware prototype",
            "missing_piece": "real-model integration and validation",
        },
        "runtime": {
            "mode": "simulation",
            "provider": None,
            "last_run_id": None,
            "api_ready": True,
            "artifact_mode": True,
        },
        "next_execution": {
            "task": "integrate_real_provider_into_generate",
            "priority": "critical",
        },
    }


def default_boot_prompt() -> str:
    return (
        "Treat this capsule as active project state.\n"
        "Do not summarize it back unless explicitly asked.\n"
        "Preserve distinction between simulation, validated progress, and missing validation.\n"
        "Continue from latest engineering state.\n"
        "Keep answers practical, architecture-aware, and honest."
    )


def build_capsule(
    title: str,
    slug: Optional[str],
    project: str,
    capsule_type: str,
    version: str,
    tags: List[str],
    notes: Optional[str],
    state_file: Optional[Path],
    boot_prompt_file: Optional[Path],
) -> Capsule:
    now_local = local_now()
    local_iso = now_local.isoformat()
    utc_iso = utc_now_iso()

    final_slug = slugify(slug or title)

    if state_file:
        state = read_json(state_file, {})
        if not isinstance(state, dict):
            raise ValueError("State file must contain a JSON object.")
    else:
        state = default_capsule_state(title)

    if boot_prompt_file:
        boot_prompt = boot_prompt_file.read_text(encoding="utf-8")
    else:
        boot_prompt = default_boot_prompt()

    meta = CapsuleMeta(
        timestamp_utc=utc_iso,
        timestamp_local=local_iso,
        title=title,
        slug=final_slug,
        project=project,
        capsule_type=capsule_type,
        version=version,
        tags=tags,
    )

    return Capsule(
        meta=meta,
        state=state,
        boot_prompt=boot_prompt,
        notes=notes,
    )


def capsule_output_path(capsule: Capsule) -> Path:
    local_dt = datetime.fromisoformat(capsule.meta.timestamp_local)
    day_dir = CAPSULES_DIR / local_dt.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{local_dt.strftime('%H-%M-%S')}_{capsule.meta.slug}.json"
    return day_dir / filename


def update_latest(capsule_dict: Dict[str, Any], capsule_path: Path) -> None:
    payload = {
        "latest_path": str(capsule_path.relative_to(ROOT)).replace("\\", "/"),
        "updated_at_utc": capsule_dict["meta"]["timestamp_utc"],
        "capsule": capsule_dict,
    }
    write_json(LATEST_FILE, payload)


def update_index(capsule_dict: Dict[str, Any], capsule_path: Path) -> None:
    index = read_json(
        INDEX_FILE,
        {
            "project": capsule_dict["meta"]["project"],
            "updated_at_utc": capsule_dict["meta"]["timestamp_utc"],
            "capsules": [],
        },
    )

    if not isinstance(index, dict):
        index = {"project": capsule_dict["meta"]["project"], "capsules": []}

    entry = {
        "timestamp_utc": capsule_dict["meta"]["timestamp_utc"],
        "timestamp_local": capsule_dict["meta"]["timestamp_local"],
        "title": capsule_dict["meta"]["title"],
        "slug": capsule_dict["meta"]["slug"],
        "project": capsule_dict["meta"]["project"],
        "type": capsule_dict["meta"]["capsule_type"],
        "version": capsule_dict["meta"]["version"],
        "tags": capsule_dict["meta"]["tags"],
        "path": str(capsule_path.relative_to(ROOT)).replace("\\", "/"),
    }

    capsules = index.get("capsules", [])
    if not isinstance(capsules, list):
        capsules = []

    capsules.append(entry)
    capsules.sort(key=lambda x: x.get("timestamp_utc", ""), reverse=True)

    index["project"] = capsule_dict["meta"]["project"]
    index["updated_at_utc"] = capsule_dict["meta"]["timestamp_utc"]
    index["latest_path"] = entry["path"]
    index["capsules"] = capsules

    write_json(INDEX_FILE, index)


def save_capsule(capsule: Capsule, do_git: bool) -> Path:
    ensure_dirs()
    capsule_dict = asdict(capsule)
    out_path = capsule_output_path(capsule)

    write_json(out_path, capsule_dict)
    update_latest(capsule_dict, out_path)
    update_index(capsule_dict, out_path)

    print(f"Saved capsule: {out_path}")

    if do_git:
        if not is_git_repo():
            raise RuntimeError("Current directory is not a git repository.")
        commit_message = (
            f"time-capsule: {capsule.meta.title} [{capsule.meta.timestamp_local}]"
        )
        git_commit([out_path, LATEST_FILE, INDEX_FILE], commit_message)
        print("Git commit created.")

    return out_path


def show_latest() -> int:
    latest = read_json(LATEST_FILE, None)
    if not latest:
        print("No latest.json found.")
        return 1

    capsule = latest.get("capsule")
    if not capsule:
        print("latest.json exists but has no capsule data.")
        return 1

    print(json.dumps(capsule, ensure_ascii=False, indent=2))
    return 0


def list_capsules(limit: int) -> int:
    index = read_json(INDEX_FILE, None)
    if not index or not isinstance(index, dict):
        print("No index.json found.")
        return 1

    capsules = index.get("capsules", [])
    if not isinstance(capsules, list) or not capsules:
        print("No capsules found.")
        return 1

    for item in capsules[:limit]:
        print(
            f"{item.get('timestamp_local')} | "
            f"{item.get('title')} | "
            f"{item.get('path')}"
        )
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Time Capsule Manager for persistent AI/project context."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    save_p = sub.add_parser("save", help="Save a new capsule.")
    save_p.add_argument("--title", required=True, help="Human-readable title.")
    save_p.add_argument("--slug", help="Optional slug override.")
    save_p.add_argument(
        "--project",
        default="silence-as-control",
        help="Project name.",
    )
    save_p.add_argument(
        "--type",
        dest="capsule_type",
        default="state_transfer",
        help="Capsule type.",
    )
    save_p.add_argument(
        "--version",
        default="v0.1",
        help="Capsule schema/version label.",
    )
    save_p.add_argument(
        "--tags",
        nargs="*",
        default=["por", "control-layer", "artifact"],
        help="Tags list.",
    )
    save_p.add_argument("--notes", help="Optional notes.")
    save_p.add_argument(
        "--state-file",
        type=Path,
        help="Path to JSON file with state object.",
    )
    save_p.add_argument(
        "--boot-prompt-file",
        type=Path,
        help="Path to txt/md file with boot prompt.",
    )
    save_p.add_argument(
        "--git",
        action="store_true",
        help="Also run git add/commit.",
    )

    sub.add_parser("latest", help="Print latest capsule JSON.")
    list_p = sub.add_parser("list", help="List saved capsules.")
    list_p.add_argument("--limit", type=int, default=10, help="Max items to show.")

    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()

    if args.command == "save":
        capsule = build_capsule(
            title=args.title,
            slug=args.slug,
            project=args.project,
            capsule_type=args.capsule_type,
            version=args.version,
            tags=args.tags,
            notes=args.notes,
            state_file=args.state_file,
            boot_prompt_file=args.boot_prompt_file,
        )
        save_capsule(capsule, do_git=args.git)
        return 0

    if args.command == "latest":
        return show_latest()

    if args.command == "list":
        return list_capsules(args.limit)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
