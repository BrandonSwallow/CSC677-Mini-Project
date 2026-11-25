"""
Verify the report's four graphs against a fresh run of the simulator.

What it does
------------
1. Re-runs every simulation behind Figures 1-4 from scratch (it does NOT read
   results/; it calls sliding_window_sim.py directly with the same seeds).
2. Compares each recomputed point (mean, min, max over seeds 0-9) with the
   value plotted in the report, stored in report_figures.json.
3. Recomputes every theory value from the textbook formulas, independently of
   the simulator's own theoretical_utilization(), and compares those too.
4. Redraws the four figures as PNGs in verify_out/ so you can compare them
   side by side with the graphs in the report.

Usage
-----
    python verify_graphs.py            # full check, about 1 minute
    python verify_graphs.py --no-plots # numbers only

Exit code 0 = every plotted value reproduced; 1 = at least one mismatch
(the mismatching points are listed).
"""
import json
import os
import statistics as st
import sys

from sliding_window_sim import SlidingWindowSimulator

SEEDS = range(10)
FRAMES = 2000
TOL = 0.0001          # report values are rounded to 4 decimal places
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "verify_out")


# ---------- independent theory (written out again, not imported) ----------
def theory(proto, p, a, W):
    pipe = 2 * a + 1
    if proto == "SW":
        return (1 - p) / pipe
    if proto == "SR":
        return (1 - p) if W >= pipe else W * (1 - p) / pipe
    if W >= pipe:                                   # GBN
        return (1 - p) / (1 + 2 * a * p)
    return W * (1 - p) / (pipe * (1 - p + W * p))


# ---------- the settings behind each figure ----------
FIGS = {
    "fig1_utilization_vs_loss": dict(
        metric="utilization", x="loss",
        settings=lambda proto, x: dict(delay=5, loss_rate=x, ack_loss=0.0, window=32),
        theory=lambda proto, x: theory(proto, x, 5, 1 if proto == "SW" else 32),
        title="Fig 1: utilization vs loss rate (a = 5, W = 32)", xlabel="Frame loss rate"),
    "fig2_utilization_vs_window": dict(
        metric="utilization", x="window",
        settings=lambda proto, x: dict(delay=5, loss_rate=0.1, ack_loss=0.0, window=int(x)),
        theory=lambda proto, x: theory(proto, 0.1, 5, x),
        title="Fig 2: utilization vs window (a = 5, p = 0.1)", xlabel="Sender window W"),
    "fig3_utilization_vs_delay": dict(
        metric="utilization", x="delay",
        settings=lambda proto, x: dict(delay=x, loss_rate=0.05, ack_loss=0.0, window=8),
        theory=lambda proto, x: theory(proto, 0.05, x, 1 if proto == "SW" else 8),
        title="Fig 3: utilization vs delay (p = 0.05, W = 8)", xlabel="a (log scale)"),
    "fig4_retransmissions_vs_loss": dict(
        metric="retx_per_frame", x="loss",
        settings=lambda proto, x: dict(delay=5, loss_rate=x, ack_loss=0.0, window=32),
        theory=None,
        title="Fig 4: retransmissions per delivered frame (a = 5, W = 32)", xlabel="Frame loss rate"),
}


def rerun(proto, metric, kw):
    vals = [getattr(SlidingWindowSimulator(protocol=proto, total_frames=FRAMES, seed=s, **kw).run(),
                    metric) for s in SEEDS]
    return st.mean(vals), min(vals), max(vals)


def main():
    plots = "--no-plots" not in sys.argv
    report = json.load(open(os.path.join(HERE, "report_figures.json")))
    failures, checked, recomputed = [], 0, {}

    for fig, spec in FIGS.items():
        print(f"\n{spec['title']}")
        recomputed[fig] = []
        worst = 0.0
        for row in report[fig]:
            proto, x = row["proto"], row["x"]
            mean, lo, hi = rerun(proto, spec["metric"], spec["settings"](proto, x))
            got = {"sim": mean, "lo": lo, "hi": hi}
            if spec["theory"]:
                got["theory"] = spec["theory"](proto, x)
            recomputed[fig].append(dict(proto=proto, x=x, **got))
            for key, value in got.items():
                checked += 1
                diff = abs(value - row[key])
                worst = max(worst, diff)
                if diff > TOL:
                    failures.append(f"{fig} {proto} x={x} {key}: report {row[key]} vs rerun {value:.4f}")
        print(f"  {len(report[fig])} points, worst difference {worst:.6f}"
              f" -> {'OK' if worst <= TOL else 'MISMATCH'}")

    print(f"\nChecked {checked} plotted values (mean, min, max and theory).")
    if failures:
        print(f"{len(failures)} MISMATCHES:")
        print("\n".join("  " + f for f in failures))
    else:
        print("All plotted values reproduced to within 0.0001.")

    os.makedirs(OUT, exist_ok=True)
    json.dump(recomputed, open(os.path.join(OUT, "recomputed_values.json"), "w"), indent=1)
    if plots:
        draw(recomputed)
        print(f"Redrawn figures written to {OUT}/")
    return 1 if failures else 0


def draw(recomputed):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"SR": "#2a78d6", "GBN": "#e8693a", "SW": "#22a87b"}
    names = {"SR": "Selective Repeat", "GBN": "Go-Back-N", "SW": "Stop-and-Wait"}
    for fig, spec in FIGS.items():
        rows = recomputed[fig]
        f, ax = plt.subplots(figsize=(8, 4.6), dpi=130)
        for proto in ("SR", "GBN", "SW"):
            pts = sorted((r for r in rows if r["proto"] == proto), key=lambda r: r["x"])
            if not pts:
                continue
            xs = [r["x"] for r in pts]
            ys = [r["sim"] for r in pts]
            err = [[r["sim"] - r["lo"] for r in pts], [r["hi"] - r["sim"] for r in pts]]
            ax.errorbar(xs, ys, yerr=err, fmt="o", ms=4, color=colors[proto],
                        label=f"{names[proto]} (simulated)")
            if spec["theory"]:
                lo_x, hi_x = min(xs), max(xs)
                n = 200
                if spec["x"] == "delay":
                    grid = [lo_x * (hi_x / lo_x) ** (i / n) for i in range(n + 1)]
                else:
                    grid = [lo_x + (hi_x - lo_x) * i / n for i in range(n + 1)]
                ax.plot(grid, [spec["theory"](proto, g) for g in grid], color=colors[proto],
                        alpha=0.55, lw=1.6, label=f"{names[proto]} (theory)")
            else:
                ax.plot(xs, ys, color=colors[proto], alpha=0.55, lw=1.6)
        if spec["x"] == "delay":
            ax.set_xscale("log")
        if spec["metric"] == "utilization":
            ax.set_ylim(0, 1.02)
            ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
            ax.set_ylabel("Link utilization")
        else:
            ax.set_ylabel("Retransmissions per delivered frame")
        if spec["x"] == "loss":
            ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        ax.set_xlabel(spec["xlabel"])
        ax.set_title(spec["title"], fontsize=11, loc="left")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7.5, ncol=2)
        f.tight_layout()
        f.savefig(os.path.join(OUT, f"{fig}.png"))
        plt.close(f)


if __name__ == "__main__":
    sys.exit(main())
