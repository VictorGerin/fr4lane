* INV — inversor CDL por inibição de fluxo magnético: W1 recebe polarização positiva de VDD (RB) e A excita o enrolamento de inibição WB via D1
.subckt INV A Y VDD GND
RB VDD w1  10k
D1 A   d1  DIODE
R1 d1  wb  3.3k
RL Y   GND 2.2k
T1 w1  GND wb Y GND CORE
.ends INV
