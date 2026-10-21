* NAND2 — NAND de 2 entradas CTL por coincidência de corrente (1 núcleo + 1 NPN)
* O enrolamento de polarização WB recebe -I_bias de VDD (via RB = 13.3k), cancelando o
* fluxo de uma única entrada alta (Immf = +I0 - I_bias < Ic). O núcleo T1 só comuta
* quando A=1 e B=1 simultaneamente (Immf = +2*I0 - I_bias >= Ic), saturando Q1 (Y=0).
.subckt NAND2 A B Y VDD GND
RL VDD Y   1k
R1 A   w1  10k
R2 B   w2  10k
RB VDD wb  13.3k
T1 w1  w2  wb  b1 GND CORE
Q1 Y   b1  GND NPN
.ends NAND2
