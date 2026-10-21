* BUF — buffer CDL não-inversor: A excita o enrolamento positivo W1 via D1 e regenera Y em um único núcleo
.subckt BUF A Y VDD GND
D1 A   d1  DIODE
R1 d1  w1  6.8k
RL Y   GND 2.2k
T1 w1  GND GND Y GND CORE
.ends BUF
