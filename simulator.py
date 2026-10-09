import heapq
import random

# ==========================================
# 1. The Discrete-Event Simulation Engine
# ==========================================
class Event:
    """Represents a single event in the simulation."""
    _counter = 0  # tie-breaker so equal-time events run in scheduling order

    def __init__(self, time, event_type, payload=None):
        self.time = time
        Event._counter += 1
        self.order = Event._counter
        self.event_type = event_type
        self.payload = payload or {}

    # This allows heapq to sort events by time
    def __lt__(self, other):
        return (self.time, self.order) < (other.time, other.order)

class EventEngine:
    """Manages the simulated clock and the event queue."""
    def __init__(self):
        self.event_queue = []
        self.current_time = 0.0
        self.handler = None # Will be set by the main Simulator class

    def schedule(self, time, event_type, payload=None):
        """Adds a new event to the priority queue."""
        heapq.heappush(self.event_queue, Event(time, event_type, payload))

    def run(self, max_time=50.0):
        """Runs the simulation until max_time is reached or queue is empty."""
        while self.event_queue:
            if self.event_queue[0].time > max_time:
                break
            event = heapq.heappop(self.event_queue)
            self.current_time = event.time
            if self.handler:
                self.handler(event)


# ==========================================
# 2. The Network Channel
# ==========================================
class Channel:
    """Simulates a network link with propagation delay and frame loss."""
    def __init__(self, engine, delay, loss_rate, direction_name):
        self.engine = engine
        self.delay = delay
        self.loss_rate = loss_rate
        self.direction_name = direction_name

    def transmit(self, frame_num):
        """Attempts to send a frame. May drop it based on loss_rate."""
        if random.random() < self.loss_rate:
            print(f"[{self.engine.current_time:5.2f}] {self.direction_name} channel DROPPED frame {frame_num}")
            return
        
        # If not dropped, schedule its arrival
        arrival_time = self.engine.current_time + self.delay
        arrival_event = f"{self.direction_name.lower()}_arrive"
        self.engine.schedule(arrival_time, arrival_event, {"frame": frame_num})


# ==========================================
# 3. The Sender (Stop-and-Wait)
# ==========================================
class StopAndWaitSender:
    def __init__(self, engine, forward_channel, timeout_duration):
        self.engine = engine
        self.channel = forward_channel
        self.timeout_duration = timeout_duration
        
        self.next_seq_num = 0
        self.window_full = False # In Stop-and-Wait, window size is 1

    def send_frame(self):
        if not self.window_full:
            print(f"[{self.engine.current_time:5.2f}] SENDER -> Sending frame {self.next_seq_num}")
            self._transmit_and_start_timer()

    def _transmit_and_start_timer(self):
        """Puts the current frame on the wire and (re)starts its timer."""
        self.channel.transmit(self.next_seq_num)
        self.window_full = True
        # Tag the timer with the frame it guards, so a stale timer
        # for an already-ACKed frame can be recognized and ignored.
        timeout_time = self.engine.current_time + self.timeout_duration
        self.engine.schedule(timeout_time, "sender_timeout", {"frame": self.next_seq_num})

    def receive_ack(self, ack_num):
        if ack_num == self.next_seq_num:
            print(f"[{self.engine.current_time:5.2f}] SENDER <- Received ACK {ack_num}")
            self.next_seq_num += 1
            self.window_full = False
            # Immediately send the next frame
            self.send_frame()
        else:
            print(f"[{self.engine.current_time:5.2f}] SENDER <- Ignored duplicate ACK {ack_num}")

    def timeout(self, frame_num):
        # Ignore timers for frames that have already been ACKed
        if self.window_full and frame_num == self.next_seq_num:
            print(f"[{self.engine.current_time:5.2f}] SENDER !! TIMEOUT! Retransmitting frame {self.next_seq_num}")
            self._transmit_and_start_timer()


# ==========================================
# 4. The Receiver
# ==========================================
class Receiver:
    def __init__(self, engine, backward_channel):
        self.engine = engine
        self.channel = backward_channel
        self.expected_seq_num = 0

    def receive_frame(self, frame_num):
        if frame_num == self.expected_seq_num:
            print(f"[{self.engine.current_time:5.2f}] RECEIVER <- ACCEPTED frame {frame_num}")
            self.expected_seq_num += 1
        else:
            print(f"[{self.engine.current_time:5.2f}] RECEIVER <- DISCARDED duplicate frame {frame_num}")
        
        # In Stop-and-Wait, the receiver always sends an ACK for the frame it just received
        self.channel.transmit(frame_num)


# ==========================================
# 5. Tying it all together
# ==========================================
class NetworkSimulator:
    def __init__(self, delay=2.0, loss_rate=0.2, timeout=6.0):
        self.engine = EventEngine()
        self.engine.handler = self.handle_event # Link the engine to our handler

        # Create channels (Forward = Sender to Receiver, Backward = Receiver to Sender)
        self.forward_channel = Channel(self.engine, delay, loss_rate, "FORWARD")
        self.backward_channel = Channel(self.engine, delay, loss_rate, "BACKWARD")

        # Create protocol entities
        self.sender = StopAndWaitSender(self.engine, self.forward_channel, timeout)
        self.receiver = Receiver(self.engine, self.backward_channel)

    def handle_event(self, event):
        """Routes events from the engine to the correct protocol entity."""
        if event.event_type == "forward_arrive":
            self.receiver.receive_frame(event.payload["frame"])
            
        elif event.event_type == "backward_arrive":
            self.sender.receive_ack(event.payload["frame"])
            
        elif event.event_type == "sender_timeout":
            self.sender.timeout(event.payload["frame"])

    def start(self, max_time=30.0):
        print("--- Starting Stop-and-Wait Simulation ---")
        # Send the first frame at time 0.0
        self.sender.send_frame()
        
        # Run the engine
        self.engine.run(max_time)
        print("--- Simulation Finished ---")


# Run the simulation
if __name__ == "__main__":
    # Parameters: propagation delay=2.0, loss rate=20%, timeout=6.0
    sim = NetworkSimulator(delay=2.0, loss_rate=0.2, timeout=6.0)
    sim.start(max_time=30.0)