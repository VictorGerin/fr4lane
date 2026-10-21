* NAND2 — porta NAND a válvulas termiônicas (2 válvulas em série cascode)
.subckt NAND2 A B Y VDD GND
RL VDD Y  10k
R1 A   g1 47k
R2 B   g2 47k
V1 Y   g1 m   TUBE
V2 m   g2 GND TUBE
.ends NAND2
