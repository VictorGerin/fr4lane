* NOR2 — NOR de 2 entradas RTL
* Q<nome> coletor base emissor modelo
* RL = resistor de coletor (pull-up), R1..R3 = resistores de base
.subckt NOR2 A B Y VDD GND
RL VDD Y  1k
R1 A   b1 10k
R2 B   b2 10k
Q1 Y   b1 GND NPN
Q2 Y   b2 GND NPN
.ends NOR2
