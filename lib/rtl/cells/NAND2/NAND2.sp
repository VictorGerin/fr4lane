* NAND2 — NAND de 2 entradas RTL (NPNs em série)
* Q<nome> coletor base emissor modelo
* RL = resistor de coletor (pull-up), R1..R2 = resistores de base
* Q1 e Q2 empilhados: Y só vai a 0 com os dois conduzindo (VOL ~ 2 Vce(sat))
.subckt NAND2 A B Y VDD GND
RL VDD Y  1k
R1 A   b1 10k
R2 B   b2 10k
Q1 Y   b1 n1  NPN
Q2 n1  b2 GND NPN
.ends NAND2
