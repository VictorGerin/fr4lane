* INV — inversor DTL com diodo de entrada D1, 2 diodos de level-shift (DS1/DS2), pull-down de base RB e 1 NPN
.subckt INV A Y VDD GND
R1  VDD d1  4.7k
D1  d1  A   DIODE
DS1 d1  m1  DIODE
DS2 m1  b1  DIODE
RB  b1  GND 10k
RL  VDD Y   1.5k
Q1  Y   b1  GND NPN
.ends INV
