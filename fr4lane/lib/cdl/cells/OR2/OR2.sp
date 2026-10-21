* OR2 — porta OU CDL em um único núcleo: D1 e D2 isolam A e B e somam corrente no enrolamento positivo W1
.subckt OR2 A B Y VDD GND
D1 A   d1  DIODE
D2 B   d1  DIODE
R1 d1  w1  6.8k
RL Y   GND 2.2k
T1 w1  GND GND Y GND CORE
.ends OR2
