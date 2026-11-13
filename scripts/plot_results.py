"""Render the included session result data; install the optional plots extra."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=Path, help="Optional local PNG preview")
    args = parser.parse_args()
    source = ROOT / "experiments/session_results/results.json"
    summary = json.loads(source.read_text(encoding="utf-8"))["summary"]
    policies = ("off", "nominal", "guarded")
    labels = ("Control off", "Nominal", "Guarded")
    colors = ("#64748b", "#2563eb", "#7c3aed")
    matplotlib.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "svg.fonttype": "none",
            "svg.hashsalt": "gridsense-session-results",
        }
    )
    figure, axes = plt.subplots(1, 2, figsize=(10.8, 4.5), layout="constrained")
    for axis, key, title, unit in (
        (axes[0], "unserved_kwh", "Accumulated unserved energy", "kWh"),
        (axes[1], "violation_ticks", "Violating physical snapshots", "Count"),
    ):
        values = [summary[policy][key] for policy in policies]
        bars = axis.bar(labels, values, color=colors, width=0.62)
        axis.bar_label(
            bars,
            labels=[f"{value:.2f}" if key == "unserved_kwh" else str(value) for value in values],
            padding=5,
            fontsize=11,
        )
        axis.set_title(title, fontsize=12, pad=14)
        axis.set_ylabel(unit)
        axis.set_ylim(0, max(values) * 1.23)
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="y", alpha=0.18)
        axis.set_axisbelow(True)
        if key == "violation_ticks":
            axis.set_yticks(range(max(values) + 1))
    episodes = {summary[policy]["episodes"] for policy in policies}
    if len(episodes) != 1:
        raise ValueError("Figure requires the same case count for each policy")
    figure.suptitle("Clocked restoration: service and constraint trade-off", fontsize=15)
    figure.supxlabel(
        f"{episodes.pop()} fixed synthetic scenarios per policy; case-specific results, not field reliability.",
        fontsize=9,
    )
    output = ROOT / "docs/figures/session-outcomes.svg"
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, metadata={"Date": None, "Creator": "GridSense result plot"})
    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(args.preview, dpi=140)
    print(output.relative_to(ROOT))
    plt.close(figure)


if __name__ == "__main__":
    main()
