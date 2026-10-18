* NOR3 — NOR de 3 entradas RTL
* Q<nome> coletor base emissor modelo
* RL = resistor de coletor (pull-up), R1..R3 = resistores de base
.subckt NOR3 A B C Y VDD GND
RL VDD Y  1k
R1 A   b1 10k
R2 B   b2 10k
R3 C   b3 10k
Q1 Y   b1 GND NPN
Q2 Y   b2 GND NPN
Q3 Y   b3 GND NPN
.ends NOR3
