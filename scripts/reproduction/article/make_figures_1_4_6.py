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
    from matplotlib.patches import FancyBboxPatch

    OUT = WORK / "figures"
    OUT.mkdir(parents=True, exist_ok=True)
    OLD = DATA / "examples" / "order-fulfilment"
    NAVY = "#18384c"
    TEAL = "#267f83"
    ORANGE = "#c86a2b"
    LIGHT = "#edf3f6"
    GREY = "#5b6570"
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "text.color": NAVY,
            "axes.labelcolor": NAVY,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
        }
    )

    def diagram(height: Any = 4.6) -> Any:
        """Apply the archived example procedure."""
        (f, a) = plt.subplots(figsize=(8, height))
        a.set(xlim=(0, 10), ylim=(0, 6))
        a.axis("off")
        f.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.98)
        return (f, a)

    def box(
        a: Any,
        x: Any,
        y: Any,
        w: Any,
        h: Any,
        text: Any,
        fc: Any = LIGHT,
        ec: Any = NAVY,
        size: Any = 10,
    ) -> Any:
        """Apply the archived example procedure."""
        a.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0.05,rounding_size=0.06",
                facecolor=fc,
                edgecolor=ec,
                linewidth=1,
            )
        )
        a.text(
            x + w / 2,
            y + h / 2,
            text,
            ha="center",
            va="center",
            fontsize=size,
            linespacing=1.4,
        )

    def arrow(
        a: Any, x1: Any, y1: Any, x2: Any, y2: Any, color: Any = NAVY, style: Any = "->"
    ) -> Any:
        """Apply the archived example procedure."""
        a.annotate(
            "",
            (x2, y2),
            (x1, y1),
            arrowprops=dict(
                arrowstyle=style, color=color, lw=1.25, shrinkA=2, shrinkB=2
            ),
        )

    def save(f: Any, n: Any) -> None:
        """Write the evidence as JSON."""
        for ext in ["png", "pdf", "svg"]:
            f.savefig(OUT / f"figure-{n}.{ext}", dpi=300, facecolor="white")
        plt.close(f)

    (f, a) = diagram(4.8)
    box(
        a,
        0.25,
        4.6,
        4.2,
        1.05,
        "Demonstration clients\nor external research harness",
        size=9.5,
    )
    box(
        a,
        5.6,
        4.6,
        4.1,
        1.05,
        "Optional benchmark layer\nComparators, references, economic scores",
        fc="#e5f1ef",
        ec=TEAL,
        size=9.5,
    )
    box(
        a,
        1.95,
        2.75,
        6.1,
        1.05,
        "HTTP/JSON service\nValidation \u2022 lifecycle \u2022 observation \u2022 checks",
    )
    box(a, 0.4, 0.65, 4.2, 1.05, "Simulation engine\nState transitions and accounting")
    box(
        a,
        5.4,
        0.65,
        4.2,
        1.05,
        "Persistent records\nWorlds, actions, outcomes and traces",
    )
    arrow(a, 2.35, 4.55, 3.6, 3.85, style="<->")
    arrow(a, 7.65, 4.55, 6.4, 3.85, style="<->")
    arrow(a, 3.6, 2.7, 2.5, 1.75, style="<->")
    arrow(a, 6.4, 2.7, 7.5, 1.75, style="<->")
    a.text(
        5,
        0.12,
        "Service coordinates execution, replay, forks and export",
        ha="center",
        fontsize=9.5,
    )
    save(f, 1)
    (f, a) = diagram(4.5)
    a.text(0.25, 5.65, "A  Shared process consequences", fontweight="bold")
    for x, text in [
        (0.25, "Procurement"),
        (2.8, "Production"),
        (5.35, "Shipment"),
        (7.9, "Customer\npayment"),
    ]:
        box(a, x, 4.25, 1.85, 0.85, text)
    for x in [2.1, 4.65, 7.2]:
        arrow(a, x, 4.68, x + 0.65, 4.68)
    box(
        a,
        2.8,
        2.85,
        4.4,
        0.7,
        "Cash, commitments and receivables",
        fc="#e5f1ef",
        ec=TEAL,
    )
    for x in [1.2, 3.7, 6.3, 8.8]:
        arrow(a, x, 4.2, 5, 3.6, color=TEAL)
    a.text(0.25, 2.1, "B  Demonstration recipe", fontweight="bold")
    box(a, 0.3, 0.55, 2.2, 0.9, "4 chips", fc="white")
    box(a, 3.9, 0.55, 2.2, 0.9, "2 boards", fc="white")
    box(a, 7.5, 0.55, 2.2, 0.9, "1 monitor", fc="white")
    arrow(a, 2.55, 1, 3.85, 1)
    arrow(a, 6.15, 1, 7.45, 1)
    a.text(3.2, 1.75, "2 chips / board", ha="center", fontsize=9)
    a.text(6.8, 1.75, "2 boards / monitor", ha="center", fontsize=9)
    save(f, 2)
    (f, a) = diagram(4.5)
    labels: Any = [
        "Receive\ndeliveries",
        "Apply\nevents",
        "Build\nobservation",
        "Make\ndecisions",
        "Execute\nactions",
        "Close\nperiod",
    ]
    for i, label in enumerate(labels):
        x = 0.18 + i * 1.66
        box(a, x, 4.3, 1.35, 1, label, size=9.5)
        if i < 5:
            arrow(a, x + 1.39, 4.8, x + 1.61, 4.8)
    box(a, 2.6, 2.55, 4.8, 0.8, "Controller / research harness", fc="#e5f1ef", ec=TEAL)
    arrow(a, 4.15, 4.25, 4.15, 3.4, color=TEAL)
    arrow(a, 5.8, 3.4, 5.8, 4.25, color=TEAL)
    a.text(
        5,
        0.95,
        "Execution order\nShip \u2192 cancel \u2192 transfer \u2192 repair\nDue plans \u2192 current production \u2192 buy",
        ha="center",
        va="center",
        linespacing=1.6,
    )
    a.text(
        5,
        0.15,
        "Lead-time-one production enters stock at close; usable next period.",
        ha="center",
        fontsize=9,
    )
    save(f, 3)
    (f, a) = diagram(5.2)
    a.text(
        5,
        5.8,
        "Define objective, horizon and permitted information before comparison",
        ha="center",
        fontsize=10,
        fontweight="bold",
    )
    box(
        a,
        0.2,
        4.45,
        3,
        0.85,
        "Disclosed description\nand observations",
        fc="#e5f1ef",
        ec=TEAL,
        size=9.5,
    )
    box(
        a,
        3.5,
        4.45,
        3,
        0.85,
        "Observed state plus\nhidden parameter means",
        fc="#f7efe5",
        ec=ORANGE,
        size=9.5,
    )
    box(a, 6.8, 4.45, 3, 0.85, "Realised future world\nand observed state", size=9.5)
    box(
        a,
        0.2,
        2.75,
        3,
        1.1,
        "Observation-limited comparators\nFull horizon, rolling variants\nand myopic planning",
        size=8.5,
    )
    box(
        a,
        3.5,
        2.75,
        3,
        1.1,
        "Informed diagnostic\nParameter-disclosure comparison",
        size=8.5,
    )
    box(a, 6.8, 2.75, 3, 1.1, "Full-foresight reference\nDiagnostic outcome", size=9)
    for x, c in [(1.7, TEAL), (5, ORANGE), (8.3, NAVY)]:
        arrow(a, x, 4.4, x, 3.9, color=c)
    box(
        a,
        0.9,
        0.9,
        8.2,
        1.1,
        "Common engine execution\nEconomic and service outcomes linked to recorded actions\nPlanner outputs are heuristic; no general optimality guarantee",
        size=9,
    )
    for x in [1.7, 5, 8.3]:
        arrow(a, x, 2.7, x, 2.05)
    a.text(
        5,
        0.25,
        "Information roles are not a ranking. The no-decision baseline supplies a score anchor.",
        ha="center",
        fontsize=8.5,
    )
    save(f, 4)
    (f, axs) = plt.subplots(2, 1, figsize=(8, 5.0), sharex=True, layout="constrained")
    for name, label, color, marker in [
        ("parent", "Original schedule", TEAL, "o"),
        ("fork", "Delayed assembly", ORANGE, "s"),
    ]:
        data: Any = json.loads((OLD / f"{name}-periods.json").read_text())["periods"]
        cash: Any = [1000]
        stock: Any = [0]
        for period in data:
            if period["ledger"]:
                cash.append(float(period["ledger"][-1]["cash_after"]))
            else:
                cash.append(cash[-1])
            cl: Any = next(s for s in period["steps"] if s["step"] == "close_period")
            stock.append(float(cl["state"]["stock"]["main"]["monitor"]))
        axs[0].plot(range(6), cash, label=label, color=color, marker=marker, ms=5)
        axs[1].plot(range(6), stock, color=color, marker=marker, ms=5)
    for ax in axs:
        ax.axvline(2.5, color=GREY, ls=":", lw=1)
        ax.grid(axis="y", alpha=0.2)
        ax.set_xlim(-0.1, 5.2)
    axs[0].set_ylabel("Cash (monetary units)")
    axs[0].legend(loc="upper left", frameon=False, ncol=2, fontsize=9)
    axs[1].set_ylabel("Finished monitors")
    axs[1].set_xlabel("Period close")
    axs[1].set_xticks(range(6))
    axs[1].set_yticks([0, 2, 4])
    axs[0].set_ylim(930, 1250)
    axs[0].text(2.6, 1220, "Alternative continuation", fontsize=9, color=GREY)
    save(f, 6)


if __name__ == "__main__":
    main()
