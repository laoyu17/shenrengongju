"""Render main-paper figures from paper dataset tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from style import PALETTE, apply_style, save_dual


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def fig01_architecture(out_dir: Path) -> tuple[Path, Path]:
    fig, ax = plt.subplots(figsize=(11.5, 3.5))
    ax.axis("off")

    blocks = [
        (0.03, 0.55, 0.18, 0.32, "Config/CLI", PALETTE["blue"]),
        (0.25, 0.55, 0.20, 0.32, "SimEngine", PALETTE["green"]),
        (0.49, 0.55, 0.20, 0.32, "Scheduler/Protocol/ETM", PALETTE["orange"]),
        (0.73, 0.55, 0.22, 0.32, "EventBus + Metrics", PALETTE["purple"]),
        (0.25, 0.12, 0.70, 0.26, "Audit + ModelRelations + ResearchReport", PALETTE["red"]),
    ]
    for x, y, w, h, label, color in blocks:
        rect = plt.Rectangle((x, y), w, h, color=color, alpha=0.18, ec=color, lw=1.8)
        ax.add_patch(rect)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=10)

    arrows = [
        ((0.21, 0.71), (0.25, 0.71)),
        ((0.45, 0.71), (0.49, 0.71)),
        ((0.69, 0.71), (0.73, 0.71)),
        ((0.84, 0.55), (0.84, 0.38)),
    ]
    for (x0, y0), (x1, y1) in arrows:
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops={"arrowstyle": "->", "lw": 1.6})

    ax.set_title("Fig01. System Evidence Chain (implementation preserved, offline paper assets only)")
    return save_dual(fig, out_dir, "fig01_architecture_evidence_chain")


def _extract_case_events(counterexamples: dict[str, Any], case_id: str) -> list[dict[str, Any]]:
    for case in counterexamples.get("cases", []):
        if isinstance(case, dict) and case.get("id") == case_id and isinstance(case.get("events"), list):
            return [item for item in case["events"] if isinstance(item, dict)]
    return []


def fig02_timeline(project_root: Path, out_dir: Path) -> tuple[Path, Path]:
    counterexamples = _load_json(project_root / "examples/research_counterexamples.json")
    fail_events = _extract_case_events(counterexamples, "abort_cancel_release_visibility_fail")
    fix_events = _extract_case_events(counterexamples, "abort_cancel_release_visibility_fixed")

    fig, axes = plt.subplots(2, 1, figsize=(11.5, 6.0), sharex=True)
    for ax, events, title in [
        (axes[0], fail_events, "Fail case"),
        (axes[1], fix_events, "Fixed case"),
    ]:
        types = sorted({str(item.get("type", "Unknown")) for item in events})
        type_to_y = {name: idx for idx, name in enumerate(types)}
        xs = [float(item.get("time", 0.0)) for item in events]
        ys = [type_to_y[str(item.get("type", "Unknown"))] for item in events]
        ax.scatter(xs, ys, c=PALETTE["blue"], s=24, alpha=0.9)
        ax.plot(xs, ys, color=PALETTE["gray"], alpha=0.35, lw=1)
        ax.set_yticks(list(type_to_y.values()))
        ax.set_yticklabels(list(type_to_y.keys()))
        ax.set_title(title)
        ax.set_ylabel("event type")
    axes[1].set_xlabel("simulation time")
    fig.suptitle("Fig02. Runtime Event Timeline: fail/fix counterexample pair", y=0.99)
    fig.tight_layout()
    return save_dual(fig, out_dir, "fig02_fail_fix_timeline")


def fig03_rule_heatmap(dataset_dir: Path, out_dir: Path) -> tuple[Path, Path]:
    audit = _load_csv(dataset_dir / "audit_table.csv")
    view = audit[audit.get("check_name", pd.Series(dtype=str)) != "__case__"].copy()

    if view.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.axis("off")
        ax.text(0.5, 0.5, "No audit_table.csv data", ha="center", va="center")
        return save_dual(fig, out_dir, "fig03_rule_closure_heatmap")

    view["score"] = view["check_passed"].astype(str).str.lower().map({"true": 1.0, "false": 0.0}).fillna(0.0)
    pivot = view.pivot_table(index="case_id", columns="check_name", values="score", aggfunc="mean", fill_value=0.0)

    fig, ax = plt.subplots(figsize=(12, max(4, 0.35 * len(pivot.index))))
    im = ax.imshow(pivot.values, cmap="RdYlGn", vmin=0.0, vmax=1.0, aspect="auto")
    ax.set_xticks(np.arange(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=45, ha="right")
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_title("Fig03. Rule closure heatmap across research counterexamples")
    fig.colorbar(im, ax=ax, fraction=0.02, pad=0.02, label="pass=1 / fail=0")
    fig.tight_layout()
    return save_dual(fig, out_dir, "fig03_rule_closure_heatmap")


def fig04_profiles(project_root: Path, out_dir: Path) -> tuple[Path, Path]:
    audit = _load_json(project_root / "artifacts/research/audit.json")
    profiles = (
        audit.get("compliance_profiles", {})
        .get("profiles", {})
        if isinstance(audit.get("compliance_profiles"), dict)
        else {}
    )

    names = ["engineering_v1", "research_v1"]
    rates = []
    labels = []
    for name in names:
        payload = profiles.get(name, {}) if isinstance(profiles, dict) else {}
        rates.append(float(payload.get("pass_rate", 0.0) or 0.0))
        labels.append(str(payload.get("status", "unknown")))

    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    bars = ax.bar(names, rates, color=[PALETTE["green"], PALETTE["orange"]], alpha=0.85)
    ax.set_ylim(0.0, 1.05)
    ax.set_ylabel("pass rate")
    ax.set_title("Fig04. Compliance profile status and pass-rate")
    for bar, label in zip(bars, labels, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.03, label, ha="center", va="bottom")
    fig.tight_layout()
    return save_dual(fig, out_dir, "fig04_compliance_profiles")


def fig05_time_deterministic_assets(dataset_dir: Path, out_dir: Path) -> tuple[Path, Path]:
    proof = _load_csv(dataset_dir / "proof_assets_table.csv")
    td = proof[proof.get("section", pd.Series(dtype=str)) == "time_deterministic_proof_assets"].copy()

    target_keys = ["max_ready_lag", "max_phase_jitter"]
    values = []
    for key in target_keys:
        row = td[td.get("metric", pd.Series(dtype=str)) == key]
        value = float(row.iloc[0]["value"]) if not row.empty else 0.0
        values.append(value)

    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    ax.bar(target_keys, values, color=[PALETTE["blue"], PALETTE["purple"]], alpha=0.9)
    ax.set_ylabel("value")
    ax.set_title("Fig05. Time-deterministic proof assets")
    fig.tight_layout()
    return save_dual(fig, out_dir, "fig05_time_deterministic_proof_assets")


def fig06_policy_ablation(dataset_dir: Path, out_dir: Path) -> tuple[Path, Path]:
    audit = _load_csv(dataset_dir / "audit_table.csv")
    view = audit[
        (audit.get("group", pd.Series(dtype=str)) == "resource_partial_hold_on_block")
        & (audit.get("check_name", pd.Series(dtype=str)) == "resource_partial_hold_on_block")
    ].copy()

    def _variant(case_id: str) -> str:
        if case_id.endswith("_fixed"):
            return "fixed"
        if case_id.endswith("_fail"):
            return "fail"
        return "other"

    if view.empty:
        labels = ["fail", "fixed"]
        vals = [0, 0]
    else:
        view["variant"] = view["case_id"].astype(str).map(_variant)
        grouped = view.groupby("variant", dropna=False)["issue_count"].mean()
        labels = ["fail", "fixed"]
        vals = [float(grouped.get("fail", 0.0)), float(grouped.get("fixed", 0.0))]

    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    ax.bar(labels, vals, color=[PALETTE["red"], PALETTE["green"]], alpha=0.9)
    ax.set_ylabel("mean issue count")
    ax.set_title("Fig06. Resource policy ablation (fail vs fixed)")
    fig.tight_layout()
    return save_dual(fig, out_dir, "fig06_resource_policy_ablation")


def fig07_scalability(dataset_dir: Path, out_dir: Path) -> tuple[Path, Path]:
    perf = _load_csv(dataset_dir / "perf_table.csv")
    if perf.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.axis("off")
        ax.text(0.5, 0.5, "No perf_table.csv data", ha="center", va="center")
        return save_dual(fig, out_dir, "fig07_scalability_ci")

    perf["task_count"] = pd.to_numeric(perf["task_count"], errors="coerce")
    perf["wall_time_ms"] = pd.to_numeric(perf["wall_time_ms"], errors="coerce")
    perf = perf.dropna(subset=["task_count", "wall_time_ms"])

    grouped = perf.groupby("task_count")
    x = np.array(sorted(grouped.groups.keys()), dtype=float)
    means = grouped["wall_time_ms"].mean().reindex(x).to_numpy()
    stds = grouped["wall_time_ms"].std(ddof=1).fillna(0.0).reindex(x).to_numpy()
    ns = grouped["wall_time_ms"].count().reindex(x).to_numpy()
    ci95 = np.where(ns > 1, 1.96 * stds / np.sqrt(ns), 0.0)

    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    ax.errorbar(x, means, yerr=ci95, fmt="o-", color=PALETTE["blue"], capsize=4, lw=1.8)
    ax.set_xlabel("task_count")
    ax.set_ylabel("wall_time_ms")
    ax.set_title("Fig07. Scalability with 95% CI over multi-seed runs")
    fig.tight_layout()
    return save_dual(fig, out_dir, "fig07_scalability_ci")


def fig08_governance_snapshot(dataset_dir: Path, out_dir: Path) -> tuple[Path, Path]:
    meta = _load_json(dataset_dir / "meta.json")
    audit = _load_csv(dataset_dir / "audit_table.csv")
    run = _load_csv(dataset_dir / "run_table.csv")

    matched_ratio = 0.0
    if not audit.empty and "matched" in audit.columns:
        case_view = audit[audit.get("check_name", pd.Series(dtype=str)) == "__case__"]
        if not case_view.empty:
            mapped = case_view["matched"].astype(str).str.lower().map({"true": 1.0, "false": 0.0}).fillna(0.0)
            matched_ratio = float(mapped.mean())

    avg_audit_issue = 0.0
    if not run.empty and "audit_issue_count" in run.columns:
        avg_audit_issue = float(pd.to_numeric(run["audit_issue_count"], errors="coerce").fillna(0.0).mean())

    lines = [
        f"git_sha: {meta.get('git_sha', 'unknown')}",
        f"pytest_passed: {meta.get('pytest_passed', 0)}",
        f"coverage_line_rate: {meta.get('coverage_line_rate', 0.0):.4f}",
        f"counterexample_matched_ratio: {matched_ratio:.2%}",
        f"avg_audit_issue_count: {avg_audit_issue:.2f}",
        f"generated_at_utc: {meta.get('generated_at_utc', '')}",
    ]

    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    ax.axis("off")
    ax.text(
        0.02,
        0.95,
        "Fig08. Reproducibility & governance snapshot",
        fontsize=12,
        fontweight="bold",
        ha="left",
        va="top",
    )
    ax.text(0.02, 0.83, "\n".join(lines), ha="left", va="top", family="monospace")
    rect = plt.Rectangle((0.015, 0.1), 0.97, 0.78, fill=False, ec=PALETTE["gray"], lw=1.1)
    ax.add_patch(rect)
    fig.tight_layout()
    return save_dual(fig, out_dir, "fig08_reproducibility_governance")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render main paper figures")
    parser.add_argument("--dataset-dir", default="artifacts/paper_data", help="dataset directory")
    parser.add_argument("--out-dir", default="artifacts/paper_figures/main", help="output figure directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    apply_style()

    project_root = Path(__file__).resolve().parents[2]
    dataset_dir = (project_root / args.dataset_dir).resolve()
    out_dir = (project_root / args.out_dir).resolve()

    outputs = [
        fig01_architecture(out_dir),
        fig02_timeline(project_root, out_dir),
        fig03_rule_heatmap(dataset_dir, out_dir),
        fig04_profiles(project_root, out_dir),
        fig05_time_deterministic_assets(dataset_dir, out_dir),
        fig06_policy_ablation(dataset_dir, out_dir),
        fig07_scalability(dataset_dir, out_dir),
        fig08_governance_snapshot(dataset_dir, out_dir),
    ]
    print(f"[INFO] generated {len(outputs)} main figures in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
