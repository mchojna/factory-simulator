"""Reproduce the archived article evidence with the current repository."""

from typing import Any


def main() -> None:
    """Reproduce this archived example."""
    import json
    import os

    from .context import DATA
    from .context import OUTPUT as WORK

    os.environ.setdefault("MPLCONFIGDIR", str(WORK / "matplotlib-cache"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    # Standalone and batch runs must not inherit another figure's style.
    with matplotlib.rc_context(rc=matplotlib.rcParamsDefault):  # pyright: ignore[reportUnknownMemberType]
        P = WORK / "figures"
        P.mkdir(parents=True, exist_ok=True)
        datafile = DATA / "notice" / "recorded-results.json"
        data: Any = json.loads(datafile.read_text())["cases"]
        controllers: Any = ["rolling", "buffered", "full_horizon", "reference"]
        labels: Any = [
            "Rolling",
            "Buffered\nrolling",
            "Full-horizon\nlimited",
            "Full-foresight\nreference",
        ]
        plt.rcParams.update(
            {
                "font.family": "DejaVu Sans",
                "font.size": 10,
                "axes.labelsize": 10,
                "axes.spines.top": False,
                "axes.spines.right": False,
                "svg.fonttype": "none",
                "pdf.fonttype": 42,
            }
        )
        fig: Any
        axes: Any
        (fig, axes) = plt.subplots(2, 1, figsize=(6.25, 4.45), sharex=True)
        x: Any = np.arange(4)
        width = 0.34
        for n, offset, color, hatch, label in [
            (0, -width / 2, "#28618e", "", "Disclosure at onset (period 3)"),
            (2, width / 2, "#d98435", "//", "Advance notice (period 1)"),
        ]:
            rows = [data[f"library_like-notice{n}-{k}"] for k in controllers]
            for ax, vals, isprofit in [
                (
                    axes[0],
                    [r["measures"]["units_shipped_on_time"] for r in rows],
                    False,
                ),
                (axes[1], [float(r["profit"]) for r in rows], True),
            ]:
                bars: Any = ax.bar(
                    x + offset,
                    vals,
                    width,
                    color=color,
                    edgecolor="white",
                    linewidth=0.7,
                    hatch=hatch,
                    label=label,
                    zorder=3,
                )
                texts = [f"{v:.2f}" if isprofit else str(v) for v in vals]
                if isprofit:
                    texts[-1] = ""
                ax.bar_label(bars, labels=texts, padding=3, fontsize=7.5)
                if isprofit and n == 2:
                    axes[1].annotate(
                        f"{vals[-1]:.2f}",
                        xy=(x[-1], vals[-1]),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha="center",
                        va="bottom",
                        fontsize=7.5,
                    )
        for ax in axes:
            ax.grid(axis="y", color="#dce1e6", linewidth=0.6, zorder=0)
            ax.set_axisbelow(True)
            ax.tick_params(axis="x", length=0)
        axes[0].set_ylabel("On-time deliveries\n(out of 40)")
        axes[0].set_ylim(0, 47)
        axes[0].set_yticks([0, 20, 40])
        axes[0].text(0, 1.05, "(a)", transform=axes[0].transAxes, weight="bold")
        axes[1].set_ylabel("Profit\n(monetary units)")
        axes[1].set_ylim(0, 2050)
        axes[1].set_yticks([0, 1000, 2000])
        axes[1].text(0, 1.05, "(b)", transform=axes[1].transAxes, weight="bold")
        axes[1].set_xticks(x, labels)
        (handles, legends) = axes[0].get_legend_handles_labels()
        fig.legend(
            handles,
            legends,
            loc="upper center",
            ncol=1,
            frameon=False,
            bbox_to_anchor=(0.55, 1),
            fontsize=9,
        )
        fig.subplots_adjust(left=0.145, right=0.99, bottom=0.15, top=0.82, hspace=0.35)
        fig.savefig(P / "figure-5.png", dpi=300, facecolor="white")
        fig.savefig(P / "figure-5.svg", facecolor="white")
        fig.savefig(P / "figure-5.pdf", facecolor="white")
        print("Saved Figure 5 formats from recorded results only.")


if __name__ == "__main__":
    main()
