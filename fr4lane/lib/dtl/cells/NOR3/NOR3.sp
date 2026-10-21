* NOR3 — porta NOR DTL de 3 entradas com OU a diodos (D1/D2/D3) e 1 único transistor NPN inversor (Q1)
.subckt NOR3 A B C Y VDD GND
R1 A   d1  6.8k
D1 d1  b1  DIODE
R2 B   d2  6.8k
D2 d2  b1  DIODE
R3 C   d3  6.8k
D3 d3  b1  DIODE
RB b1  GND 22k
RL VDD Y   1.5k
Q1 Y   b1  GND NPN
.ends NOR3
