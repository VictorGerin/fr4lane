* NOR2 — porta NOR CDL de 2 entradas: W1 recebe polarização positiva de VDD (RB) e D1/D2 inibem o núcleo pelo enrolamento WB
.subckt NOR2 A B Y VDD GND
RB VDD w1  10k
D1 A   d1  DIODE
D2 B   d1  DIODE
R1 d1  wb  3.3k
RL Y   GND 2.2k
T1 w1  GND wb Y GND CORE
.ends NOR2
