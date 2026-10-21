* NAND2 — porta NAND DTL clássica (série 930 / IBM 1401): diodos de entrada D1/D2, 2 diodos de level-shift DS1/DS2 e 1 NPN
.subckt NAND2 A B Y VDD GND
R1  VDD d1  4.7k
D1  d1  A   DIODE
D2  d1  B   DIODE
DS1 d1  m1  DIODE
DS2 m1  b1  DIODE
RB  b1  GND 10k
RL  VDD Y   1.5k
Q1  Y   b1  GND NPN
.ends NAND2
