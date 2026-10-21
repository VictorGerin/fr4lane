* NOR2 — porta NOR a válvulas termiônicas (2 válvulas em paralelo estilo ENIAC/IBM 604)
.subckt NOR2 A B Y VDD GND
RL VDD Y  10k
R1 A   g1 47k
R2 B   g2 47k
V1 Y   g1 GND TUBE
V2 Y   g2 GND TUBE
.ends NOR2
