* NOR2 — NOR de 2 entradas CTL (soma de fluxo em 1 núcleo + 1 NPN)
* Qualquer entrada alta (A=1 ou B=1) gera FMM >= Ic no toroide T1 e satura Q1 (Y=0).
.subckt NOR2 A B Y VDD GND
RL VDD Y   1k
R1 A   w1  10k
R2 B   w2  10k
T1 w1  w2  GND b1 GND CORE
Q1 Y   b1  GND NPN
.ends NOR2
