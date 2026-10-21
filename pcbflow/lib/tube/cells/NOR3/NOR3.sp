* NOR3 — porta NOR de 3 entradas a válvulas termiônicas (3 válvulas em paralelo)
.subckt NOR3 A B C Y VDD GND
RL VDD Y  10k
R1 A   g1 47k
R2 B   g2 47k
R3 C   g3 47k
V1 Y   g1 GND TUBE
V2 Y   g2 GND TUBE
V3 Y   g3 GND TUBE
.ends NOR3
