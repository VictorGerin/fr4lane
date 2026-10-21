* NAND3 — porta NAND DTL de 3 entradas em 1 único transistor NPN: diodos de entrada D1/D2/D3 + level-shift DS1/DS2
.subckt NAND3 A B C Y VDD GND
R1  VDD d1  4.7k
D1  d1  A   DIODE
D2  d1  B   DIODE
D3  d1  C   DIODE
DS1 d1  m1  DIODE
DS2 m1  b1  DIODE
RB  b1  GND 10k
RL  VDD Y   1.5k
Q1  Y   b1  GND NPN
.ends NAND3
