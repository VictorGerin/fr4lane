* INV — inversor CTL (1 núcleo toroidal de ferrite + 1 NPN + 2 resistores)
* T<nome> w1 w2 wb s gnd CORE
* Quando A=1, a corrente por R1 no enrolamento W1 comuta o núcleo e satura Q1 (Y=0).
.subckt INV A Y VDD GND
RL VDD Y   1k
R1 A   w1  10k
T1 w1  GND GND b1 GND CORE
Q1 Y   b1  GND NPN
.ends INV
