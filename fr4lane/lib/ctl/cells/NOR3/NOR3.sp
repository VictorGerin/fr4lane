* NOR3 — NOR de 3 entradas CTL (2 núcleos em paralelo alimentando 1 NPN)
* Qualquer entrada alta (A=1, B=1 ou C=1) comuta T1 ou T2 e satura Q1 (Y=0).
.subckt NOR3 A B C Y VDD GND
RL VDD Y   1k
R1 A   w1  10k
R2 B   w2  10k
R3 C   w3  10k
T1 w1  w2  GND b1 GND CORE
T2 w3  GND GND b1 GND CORE
Q1 Y   b1  GND NPN
.ends NOR3
