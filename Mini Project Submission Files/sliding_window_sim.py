"""
Sliding Window Protocol Simulator
=================================

Discrete-event simulator for three reliable data-transfer protocols over a
lossy, full-duplex link:

    * Stop-and-Wait (SW)
    * Go-Back-N (GBN)
    * Selective Repeat (SR)

It extends the seeded Stop-and-Wait notebook (`stop_and_wait_seeded.ipynb`):
same event engine (heap + tie-breaking counter) and the same per-channel
`random.Random(seed)` / `random.Random(seed + 1)` idea, so every run is
reproducible from its seed.

Additions over the notebook
---------------------------
* Frame transmission time `t_frame` (serialisation on the link) in addition to
  propagation delay, so link utilisation can be measured. ACKs are treated as
  negligibly small (zero transmission time), as in the textbook analysis.
* A sender-side link that transmits one frame at a time (frames queue).
* m-bit sequence numbers that wrap modulo 2**m, so the window-size limits
  W <= 2**m - 1 (GBN) and W <= 2**(m-1) (SR) can be tested.
* Each frame also carries the "true" payload id (ground truth that a real
  receiver could not see), so the simulator can detect when the receiver hands
  the wrong data to the upper layer.
* Optional scripted drops (`fwd_drops` / `bwd_drops`: indices of the n-th
  frame offered to a channel) for deterministic scenarios.
* Metrics: utilisation, throughput, retransmissions, timeouts.

Time unit: one frame transmission time (t_frame = 1). Propagation delay is
given in the same unit, so `delay` equals the textbook ratio a = t_prop / t_frame.
"""

import heapq
import random
import io
import contextlib
from dataclasses import dataclass, field


# ---------------------------------------------------------------- engine ---
class Event:
    _counter = 0

    def __init__(self, time, event_type, payload=None):
        self.time = time
        Event._counter += 1
        self.order = Event._counter
        self.event_type = event_type
        self.payload = payload or {}

    def __lt__(self, other):
        return (self.time, self.order) < (other.time, other.order)


class EventEngine:
    def __init__(self):
        self.event_queue = []
        self.current_time = 0.0
        self.handler = None
        self.stopped = False

    def schedule(self, time, event_type, payload=None):
        heapq.heappush(self.event_queue, Event(time, event_type, payload))

    def run(self, max_time=float("inf")):
        while self.event_queue and not self.stopped:
            if self.event_queue[0].time > max_time:
                break
            event = heapq.heappop(self.event_queue)
            self.current_time = event.time
            self.handler(event)


# --------------------------------------------------------------- tracing ---
class Tracer:
    """Collects (time, actor, text) lines; prints them if verbose."""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.lines = []

    def log(self, t, actor, text):
        line = f"[{t:7.2f}] {actor:<8} {text}"
        self.lines.append(line)
        if self.verbose:
            print(line)


# --------------------------------------------------------------- channel ---
class Channel:
    """One direction of the link: propagation delay + Bernoulli frame loss.

    `scripted_drops` (a set of 0-based offer indices) overrides the random
    loss model when given, for deterministic scenarios.
    """

    def __init__(self, engine, tracer, delay, loss_rate, name, rng=None,
                 scripted_drops=None):
        self.engine = engine
        self.tracer = tracer
        self.delay = delay
        self.loss_rate = loss_rate
        self.name = name
        self.rng = rng or random.Random()
        self.scripted_drops = scripted_drops
        self.offered = 0
        self.dropped = 0

    def transmit(self, depart_time, event_type, frame, label):
        """Frame leaves the sender's interface at depart_time (end of serialisation)."""
        idx = self.offered
        self.offered += 1
        if self.scripted_drops is not None:
            lost = idx in self.scripted_drops
        else:
            lost = self.rng.random() < self.loss_rate
        if lost:
            self.dropped += 1
            # logged when the frame finishes leaving the sender
            self.engine.schedule(depart_time, "drop_note",
                                 {"text": f"{self.name} channel DROPPED {label}"})
            return
        self.engine.schedule(depart_time + self.delay, event_type, frame)


# ------------------------------------------------------------ sender side ---
class SenderBase:
    """Common machinery. The sender owns one outgoing link that carries one
    frame at a time; whenever the link goes idle (or an ACK / timeout changes
    the window) it asks the protocol for the next frame to put on the wire."""

    def __init__(self, sim, window, seq_bits, timeout, total_frames):
        self.sim = sim
        self.engine = sim.engine
        self.tr = sim.tracer
        self.W = window
        self.M = 2 ** seq_bits
        self.timeout = timeout
        self.N = total_frames
        self.base = 0              # oldest unacknowledged frame (absolute number)
        self.next_seq = 0          # next frame to put on the wire (absolute)
        self.high_water = 0        # one past the highest frame ever transmitted
        self.link_busy = False
        self.tx_id = {}            # absolute seq -> id of its latest transmission
        self.tx_counter = 0
        self.data_tx = 0           # data-frame transmissions incl. retransmissions
        self.retx = 0
        self.timeouts = 0

    # -- link -------------------------------------------------------------
    def try_send(self):
        if self.link_busy:
            return
        seq = self.next_frame()
        if seq is None:
            return
        now = self.engine.current_time
        retransmission = seq < self.high_water
        self.high_water = max(self.high_water, seq + 1)
        self.link_busy = True
        self.tx_counter += 1
        self.tx_id[seq] = self.tx_counter
        self.data_tx += 1
        if retransmission:
            self.retx += 1
        mod = seq % self.M
        label = f"frame {mod}" + self._abs(seq)
        self.tr.log(now, "SENDER", f"-> {'Retransmit' if retransmission else 'Send'} {label}")
        finish = now + self.sim.t_frame
        self.engine.schedule(finish, "link_free")
        self.sim.fwd.transmit(finish, "frame_arrive", {"seq": mod, "data": seq}, label)
        self.engine.schedule(now + self.timeout, "timeout", {"seq": seq, "tx": self.tx_counter})

    def on_link_free(self):
        self.link_busy = False
        self.try_send()

    def _abs(self, seq):
        # show the absolute data number when the wire seq number has wrapped
        return f" (data #{seq})" if seq != seq % self.M else ""

    def window_end(self):
        return min(self.base + self.W, self.N)


class GoBackNSender(SenderBase):
    """Cumulative ACKs; one timer for the oldest unACKed frame; on timeout the
    sender goes back to `base` and resends everything from there in order."""

    def next_frame(self):
        if self.next_seq < self.window_end():
            s = self.next_seq
            self.next_seq += 1
            return s
        return None

    def on_ack(self, ack):
        # ack = next frame the receiver expects (mod M)
        k = (ack - self.base) % self.M
        if 0 < k <= self.high_water - self.base:
            self.base += k
            self.next_seq = max(self.next_seq, self.base)
            self.tr.log(self.engine.current_time, "SENDER",
                        f"<- ACK {ack} (cumulative), window base -> {self.base % self.M}")
            self.try_send()
        else:
            self.tr.log(self.engine.current_time, "SENDER", f"<- duplicate ACK {ack} ignored")

    def on_timeout(self, seq, tx):
        if seq == self.base and seq < self.high_water and self.tx_id.get(seq) == tx:
            self.timeouts += 1
            if self.W > 1:
                last = self.high_water - 1
                self.tr.log(self.engine.current_time, "SENDER",
                            f"!! TIMEOUT frame {seq % self.M}: go back, resend from "
                            f"{seq % self.M} ({self.high_water - seq} outstanding, "
                            f"up to {last % self.M})")
            else:
                self.tr.log(self.engine.current_time, "SENDER", f"!! TIMEOUT frame {seq % self.M}")
            self.next_seq = self.base
            self.try_send()


class StopAndWaitSender(GoBackNSender):
    """Window of 1 with 1-bit sequence numbers (alternating bit). The receiver
    ACKs with the number of the frame it just received."""

    def __init__(self, sim, timeout, total_frames):
        super().__init__(sim, window=1, seq_bits=1, timeout=timeout,
                         total_frames=total_frames)

    def on_ack(self, ack):
        if self.base < self.high_water and ack == self.base % self.M:
            self.tr.log(self.engine.current_time, "SENDER", f"<- ACK {ack} received")
            self.base += 1
            self.next_seq = max(self.next_seq, self.base)
            self.try_send()
        else:
            self.tr.log(self.engine.current_time, "SENDER", f"<- duplicate ACK {ack} ignored")


class SelectiveRepeatSender(SenderBase):
    """Individual ACKs; one timer per frame; only the frame that timed out is resent."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.acked = set()
        self.resend_queue = []

    def next_frame(self):
        while self.resend_queue:
            s = self.resend_queue.pop(0)
            if s >= self.base and s not in self.acked:
                return s
        if self.next_seq < self.window_end():
            s = self.next_seq
            self.next_seq += 1
            return s
        return None

    def on_ack(self, ack):
        match = None
        for s in range(self.base, self.high_water):
            if s % self.M == ack:
                match = s
                break
        if match is None or match in self.acked:
            self.tr.log(self.engine.current_time, "SENDER", f"<- duplicate ACK {ack} ignored")
            return
        self.acked.add(match)
        moved = False
        while self.base in self.acked:
            self.acked.discard(self.base)
            self.base += 1
            moved = True
        if moved:
            self.tr.log(self.engine.current_time, "SENDER",
                        f"<- ACK {ack}, window base -> {self.base % self.M}")
            self.try_send()
        else:
            self.tr.log(self.engine.current_time, "SENDER",
                        f"<- ACK {ack} (out of order; base still {self.base % self.M})")

    def on_timeout(self, seq, tx):
        if (self.base <= seq < self.high_water and seq not in self.acked
                and self.tx_id.get(seq) == tx):
            self.timeouts += 1
            self.tr.log(self.engine.current_time, "SENDER",
                        f"!! TIMEOUT frame {seq % self.M}: resend this frame only")
            self.resend_queue.append(seq)
            self.try_send()


# ---------------------------------------------------------- receiver side ---
class ReceiverBase:
    def __init__(self, sim, seq_bits, window):
        self.sim = sim
        self.engine = sim.engine
        self.tr = sim.tracer
        self.M = 2 ** seq_bits
        self.W = window
        self.delivered = []        # payload ids handed to the upper layer, in order
        self.errors = 0            # deliveries whose payload was not the expected one

    def deliver(self, data):
        expected = len(self.delivered)
        self.delivered.append(data)
        if data != expected:
            self.errors += 1
            self.tr.log(self.engine.current_time, "RECEIVER",
                        f"** ERROR: upper layer got data #{data}, expected data #{expected}")
        self.sim.on_delivery()

    def send_ack(self, ack):
        self.sim.bwd.transmit(self.engine.current_time, "ack_arrive", {"ack": ack}, f"ACK {ack}")


class StopAndWaitReceiver(ReceiverBase):
    def __init__(self, sim):
        super().__init__(sim, seq_bits=1, window=1)
        self.expected = 0

    def on_frame(self, f):
        if f["seq"] == self.expected:
            self.tr.log(self.engine.current_time, "RECEIVER", f"<- ACCEPTED frame {f['seq']}")
            self.expected = (self.expected + 1) % self.M
            self.deliver(f["data"])
        else:
            self.tr.log(self.engine.current_time, "RECEIVER",
                        f"<- DISCARDED duplicate frame {f['seq']}")
        self.send_ack(f["seq"])


class GoBackNReceiver(ReceiverBase):
    """Accepts only the next in-order frame; ACK = next expected (cumulative)."""

    def __init__(self, sim, seq_bits):
        super().__init__(sim, seq_bits=seq_bits, window=1)
        self.expected = 0

    def on_frame(self, f):
        if f["seq"] == self.expected:
            self.tr.log(self.engine.current_time, "RECEIVER", f"<- ACCEPTED frame {f['seq']}")
            self.expected = (self.expected + 1) % self.M
            self.deliver(f["data"])
        else:
            self.tr.log(self.engine.current_time, "RECEIVER",
                        f"<- DISCARDED frame {f['seq']} (out of order, expecting {self.expected})")
        self.send_ack(self.expected)


class SelectiveRepeatReceiver(ReceiverBase):
    """Buffers out-of-order frames inside its window; ACKs each frame individually."""

    def __init__(self, sim, seq_bits, window):
        super().__init__(sim, seq_bits=seq_bits, window=window)
        self.rbase = 0             # wire seq number at the bottom of the receive window
        self.buffer = {}           # wire seq -> payload

    def on_frame(self, f):
        s = f["seq"]
        offset = (s - self.rbase) % self.M
        if offset < self.W:                       # inside receive window
            if s in self.buffer:
                self.tr.log(self.engine.current_time, "RECEIVER",
                            f"<- duplicate frame {s} already buffered")
            else:
                self.buffer[s] = f["data"]
                if offset == 0:
                    self.tr.log(self.engine.current_time, "RECEIVER", f"<- ACCEPTED frame {s}")
                else:
                    self.tr.log(self.engine.current_time, "RECEIVER",
                                f"<- BUFFERED frame {s} (waiting for {self.rbase})")
                flushed = []
                while self.rbase in self.buffer:
                    flushed.append((self.rbase, self.buffer.pop(self.rbase)))
                    self.rbase = (self.rbase + 1) % self.M
                if len(flushed) > 1:
                    self.tr.log(self.engine.current_time, "RECEIVER",
                                f"   delivers {', '.join(str(s) for s, _ in flushed)} in order")
                for _, data in flushed:
                    self.deliver(data)
            self.send_ack(s)
        elif (self.rbase - s) % self.M <= self.W:  # in the previous window: re-ACK
            self.tr.log(self.engine.current_time, "RECEIVER",
                        f"<- DISCARDED old duplicate frame {s}, re-ACK")
            self.send_ack(s)
        else:
            self.tr.log(self.engine.current_time, "RECEIVER", f"<- IGNORED frame {s} (outside window)")


# -------------------------------------------------------------- simulator ---
@dataclass
class Result:
    protocol: str
    loss: float
    window: int
    delay: float
    delivered: int
    end_time: float
    data_tx: int
    retx: int
    timeouts: int
    errors: int
    utilization: float = field(init=False)
    retx_per_frame: float = field(init=False)

    def __post_init__(self):
        self.utilization = self.delivered / self.end_time if self.end_time else 0.0
        self.retx_per_frame = self.retx / self.delivered if self.delivered else 0.0


class SlidingWindowSimulator:
    """
    protocol   : 'SW', 'GBN' or 'SR'
    delay      : one-way propagation delay, in frame-times (= a)
    loss_rate  : per-frame loss probability (forward channel)
    ack_loss   : loss probability on the ACK channel (defaults to loss_rate)
    window     : sender window W (ignored for SW)
    seq_bits   : m; default is the smallest m that is legal for W
    timeout    : default = round-trip time (t_frame + 2*delay) + 0.01
    """

    def __init__(self, protocol="GBN", delay=2.0, loss_rate=0.1, ack_loss=None,
                 window=4, seq_bits=None, timeout=None, total_frames=20,
                 seed=None, verbose=False, fwd_drops=None, bwd_drops=None,
                 t_frame=1.0):
        self.protocol = protocol
        self.t_frame = t_frame
        self.delay = delay
        self.loss_rate = loss_rate
        self.ack_loss = loss_rate if ack_loss is None else ack_loss
        self.total_frames = total_frames
        self.engine = EventEngine()
        self.engine.handler = self.handle_event
        self.tracer = Tracer(verbose)
        if timeout is None:
            timeout = t_frame + 2 * delay + 0.01

        if seed is None:
            fwd_rng, bwd_rng = random.Random(), random.Random()
        else:
            fwd_rng, bwd_rng = random.Random(seed), random.Random(seed + 1)
        self.fwd = Channel(self.engine, self.tracer, delay, loss_rate, "FORWARD",
                           fwd_rng, fwd_drops)
        self.bwd = Channel(self.engine, self.tracer, delay, self.ack_loss, "BACKWARD",
                           bwd_rng, bwd_drops)

        if protocol == "SW":
            self.window = 1
            self.sender = StopAndWaitSender(self, timeout, total_frames)
            self.receiver = StopAndWaitReceiver(self)
        elif protocol == "GBN":
            self.window = window
            m = seq_bits or max(1, (window).bit_length())          # W <= 2^m - 1
            self.sender = GoBackNSender(self, window, m, timeout, total_frames)
            self.receiver = GoBackNReceiver(self, m)
        elif protocol == "SR":
            self.window = window
            m = seq_bits or max(1, (window - 1).bit_length() + 1)  # W <= 2^(m-1)
            self.sender = SelectiveRepeatSender(self, window, m, timeout, total_frames)
            self.receiver = SelectiveRepeatReceiver(self, m, window)
        else:
            raise ValueError(protocol)
        self.last_delivery = 0.0

    def handle_event(self, ev):
        t = self.engine.current_time
        if ev.event_type == "frame_arrive":
            self.receiver.on_frame(ev.payload)
        elif ev.event_type == "ack_arrive":
            self.sender.on_ack(ev.payload["ack"])
        elif ev.event_type == "timeout":
            self.sender.on_timeout(ev.payload["seq"], ev.payload["tx"])
        elif ev.event_type == "link_free":
            self.sender.on_link_free()
        elif ev.event_type == "drop_note":
            self.tracer.log(t, "CHANNEL", ev.payload["text"])

    def on_delivery(self):
        self.last_delivery = self.engine.current_time
        if len(self.receiver.delivered) >= self.total_frames:
            self.engine.stopped = True

    def run(self, max_time=float("inf")):
        name = {"SW": "Stop-and-Wait", "GBN": "Go-Back-N", "SR": "Selective Repeat"}[self.protocol]
        self.tracer.log(0.0, "SIM", f"--- {name}: W={self.window}, m={self._m()} bits, "
                                     f"a={self.delay}, loss={self.loss_rate}, "
                                     f"ack loss={self.ack_loss} ---")
        self.sender.try_send()
        self.engine.run(max_time)
        self.tracer.log(self.engine.current_time, "SIM",
                        f"--- finished: {len(self.receiver.delivered)} frames delivered, "
                        f"{self.sender.retx} retransmissions, {self.sender.timeouts} timeouts ---")
        return Result(self.protocol, self.loss_rate, self.window, self.delay,
                      len(self.receiver.delivered), self.last_delivery,
                      self.sender.data_tx, self.sender.retx, self.sender.timeouts,
                      self.receiver.errors)

    def _m(self):
        return {2: 1}.get(self.sender.M, self.sender.M.bit_length() - 1)


# ------------------------------------------------------------ theory -----
def theoretical_utilization(protocol, p, a, W=1):
    """Textbook utilisation (Stallings), with P = probability a frame is lost
    and timeout ~ one round trip."""
    if protocol == "SW":
        return (1 - p) / (1 + 2 * a)
    if protocol == "SR":
        return (1 - p) if W >= 2 * a + 1 else W * (1 - p) / (2 * a + 1)
    if protocol == "GBN":
        if W >= 2 * a + 1:
            return (1 - p) / (1 + 2 * a * p)
        return W * (1 - p) / ((2 * a + 1) * (1 - p + W * p))
    raise ValueError(protocol)


def trace(**kwargs):
    sim = SlidingWindowSimulator(**kwargs)
    res = sim.run()
    return sim.tracer.lines, res


if __name__ == "__main__":
    for proto in ("SW", "GBN", "SR"):
        lines, res = trace(protocol=proto, delay=2.0, loss_rate=0.2, window=4,
                           total_frames=8, seed=42)
        print("\n".join(lines))
        print()
