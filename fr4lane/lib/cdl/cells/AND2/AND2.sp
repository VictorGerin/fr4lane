* AND2 — porta E CDL por coincidência de corrente em um único núcleo: W1 e W2 somam A e B via D1/D2 contra a polarização de inibição WB (RB)
.subckt AND2 A B Y VDD GND
D1 A   d1  DIODE
R1 d1  w1  6.8k
D2 B   d2  DIODE
R2 d2  w2  6.8k
RB VDD wb  10k
RL Y   GND 2.2k
T1 w1  w2  wb Y GND CORE
.ends AND2
