"""Runs every experiment in the report and writes results/*.json and *.csv."""
import json, csv, os, statistics as st
from sliding_window_sim import SlidingWindowSimulator, theoretical_utilization, trace

SEEDS = range(10)
FRAMES = 2000
OUT = "results"
os.makedirs(OUT, exist_ok=True)


def point(proto, **kw):
    rs = [SlidingWindowSimulator(protocol=proto, total_frames=FRAMES, seed=s, **kw).run()
          for s in SEEDS]
    u = [r.utilization for r in rs]
    rx = [r.retx_per_frame for r in rs]
    assert all(r.errors == 0 for r in rs)
    return dict(sim=st.mean(u), lo=min(u), hi=max(u), retx=st.mean(rx),
                retx_lo=min(rx), retx_hi=max(rx),
                timeouts=st.mean(r.timeouts / r.delivered for r in rs))


def write(name, rows):
    json.dump(rows, open(f"{OUT}/{name}.json", "w"), indent=1)
    with open(f"{OUT}/{name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


# 1. Utilisation vs loss rate (a = 5, W = 32, ACK channel lossless)
A, W = 5, 32
rows = []
for p in [round(0.05 * i, 2) for i in range(11)]:
    for proto in ("SW", "GBN", "SR"):
        r = point(proto, delay=A, loss_rate=p, ack_loss=0.0, window=W)
        w = 1 if proto == "SW" else W
        rows.append(dict(proto=proto, x=p, theory=theoretical_utilization(proto, p, A, w), **r))
write("exp1_loss", rows)

# 2. Utilisation vs window size (a = 5, p = 0.1)
P = 0.1
rows = []
for w in [1, 2, 3, 4, 6, 8, 10, 11, 12, 14, 16, 20, 24, 28, 32, 40]:
    for proto in ("GBN", "SR"):
        r = point(proto, delay=A, loss_rate=P, ack_loss=0.0, window=w)
        rows.append(dict(proto=proto, x=w, theory=theoretical_utilization(proto, P, A, w), **r))
r = point("SW", delay=A, loss_rate=P, ack_loss=0.0)
rows.append(dict(proto="SW", x=1, theory=theoretical_utilization("SW", P, A), **r))
write("exp2_window", rows)

# 3. Utilisation vs propagation delay a (p = 0.05, W = 8)
P3, W3 = 0.05, 8
rows = []
for a in [0.5, 1, 2, 3.5, 5, 10, 20, 50]:
    for proto in ("SW", "GBN", "SR"):
        r = point(proto, delay=a, loss_rate=P3, ack_loss=0.0, window=W3)
        w = 1 if proto == "SW" else W3
        rows.append(dict(proto=proto, x=a, theory=theoretical_utilization(proto, P3, a, w), **r))
write("exp3_delay", rows)

# 4. ACK loss: forward loss 0.1, ACK loss 0 vs 0.1 (a = 5, W = 32)
rows = []
for proto in ("SW", "GBN", "SR"):
    for ackp in (0.0, 0.1):
        r = point(proto, delay=A, loss_rate=0.1, ack_loss=ackp, window=W)
        rows.append(dict(proto=proto, ack_loss=ackp, **r))
write("exp4_ackloss", rows)

# 5. Sequence-number limit scenarios (scripted ACK losses, no random loss)
rows = []
traces = {}
for proto, w, m in (("GBN", 3, 2), ("GBN", 4, 2), ("SR", 2, 2), ("SR", 3, 2)):
    sim = SlidingWindowSimulator(protocol=proto, delay=2.0, loss_rate=0.0, window=w,
                                 seq_bits=m, total_frames=6, fwd_drops=set(),
                                 bwd_drops=set(range(w)))
    res = sim.run()
    limit = 2 ** m - 1 if proto == "GBN" else 2 ** (m - 1)
    rows.append(dict(proto=proto, m=m, window=w, limit=limit, legal=w <= limit,
                     errors=res.errors, delivered=res.delivered))
    traces[f"{proto}_W{w}_m{m}"] = sim.tracer.lines
write("exp5_seqlimit", rows)

# 6. Sample traces (same seed for all three protocols)
for proto, n in (("SW", 4), ("GBN", 4), ("SR", 4)):
    lines, _ = trace(protocol=proto, delay=2.0, loss_rate=0.2, window=4, total_frames=n, seed=42)
    traces[f"sample_{proto}"] = lines
json.dump(traces, open(f"{OUT}/traces.json", "w"), indent=1)
for k, v in traces.items():
    open(f"{OUT}/trace_{k}.txt", "w").write("\n".join(v) + "\n")
print("done")
