Mini Project Proposal: Sliding Window Protocol Simulator
Oct 9, 2026 
Summary
Project title: Sliding Window Protocol Simulator
I will build a discrete-event simulator in Python that runs Stop-and-Wait, Go-Back-N, and Selective Repeat over a lossy channel. The frame loss rate, window size, and propagation delay are set as run parameters, and each run produces an event trace showing how the protocol responds to lost frames and ACKs. I will then measure the efficiency of each protocol and compare the simulated results against the theoretical utilization formulas. The scope is sized to be completed by mid-November.
How the project addresses the MS course outcomes
Outcome 4 – Implement seven-layer computer network architecture and their corresponding protocols. I will implement three reliable data transfer protocols used at the data-link layer (and underlying transport-layer reliability in TCP), including sequence numbering, acknowledgments, timeouts, retransmission, and receiver-side buffering for Selective Repeat.
Outcome 5 – Integrate flow control and various ways of enforcing it within a TCP/IP environment. The project centers on sliding window flow control. I will show how window size limits the number of unacknowledged frames in transit and how each protocol enforces this differently. The report will explain how the sequence number space limits the maximum window size (W ≤ 2^m − 1 for Go-Back-N and W ≤ 2^(m−1) for Selective Repeat), and the simulator will include an example scenario showing the error that occurs when the Selective Repeat limit is violated.
Outcome 6 – Develop simulated computer network features to visualize different computer network protocols. I will build a discrete-event simulation with a lossy channel model. Each run produces an event trace of frames sent, frames and ACKs lost, timeouts, and retransmissions, so the behavior of each protocol can be followed step by step. Performance results are visualized as graphs.
Outcome 7 – Validate network protocols and determine their efficiency to solve modern network problems. I will measure link utilization, throughput, and number of retransmissions across a range of loss rates and window sizes. I will validate the simulator by plotting simulated utilization against the theoretical formulas for each protocol, and analyze which protocol performs best under different network conditions (e.g., high-latency or high-loss links).
Deliverables
•	Python source code for the simulator
•	A written report with experiment results, graphs, and analysis, including sample event traces from each protocol
