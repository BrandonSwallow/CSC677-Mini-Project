# Sliding Window Protocol Simulator

- `sliding_window_sim.py` – discrete-event simulator for Stop-and-Wait, Go-Back-N and Selective Repeat
  (extends `stop_and_wait_seeded.ipynb`: same event engine and seeded per-channel RNGs).
- `experiments.py` – runs every experiment in the report (about 1 minute) and writes `results/`.
- `results/` – CSV/JSON for each experiment and the event traces quoted in the report.

Quick trace:

```python
from sliding_window_sim import trace
lines, res = trace(protocol="SR", delay=2.0, loss_rate=0.2, window=4, total_frames=4, seed=42)
print("\n".join(lines))
```

## Verifying the report's graphs

```
python verify_graphs.py
```

Re-runs every simulation behind Figures 1–4 from scratch (same seeds 0–9, 2,000 frames),
compares each plotted point (mean, min, max) and each theory value with the numbers the
report plots (`report_figures.json`), and redraws the four figures to `verify_out/` for a
visual side-by-side. Exit code 0 means everything reproduced to within 0.0001.
Add `--no-plots` to check the numbers only.
