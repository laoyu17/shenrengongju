"""Export paper figure manifest with file hashes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_files(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        rows.append(
            {
                "path": rel,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export paper figure manifest")
    parser.add_argument("--figures-root", default="artifacts/paper_figures", help="figure output root")
    parser.add_argument("--dataset-dir", default="artifacts/paper_data", help="paper dataset directory")
    parser.add_argument(
        "--prompt-file",
        default="scripts/paper_assets/prompt_nano_banana.md",
        help="concept prompt markdown file",
    )
    parser.add_argument(
        "--out",
        default="artifacts/paper_figures/manifest.json",
        help="manifest output path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    figures_root = (project_root / args.figures_root).resolve()
    dataset_dir = (project_root / args.dataset_dir).resolve()
    prompt_file = (project_root / args.prompt_file).resolve()
    out_path = (project_root / args.out).resolve()

    manifest = {
        "generated_at_utc": _utc_now(),
        "figures_root": str(figures_root),
        "dataset_dir": str(dataset_dir),
        "main": _collect_files(figures_root / "main"),
        "appendix": _collect_files(figures_root / "appendix"),
        "concept": _collect_files(figures_root / "concept"),
        "dataset": _collect_files(dataset_dir),
        "prompt": {
            "path": str(prompt_file),
            "exists": prompt_file.exists(),
            "sha256": _sha256(prompt_file) if prompt_file.exists() else None,
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] manifest written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
