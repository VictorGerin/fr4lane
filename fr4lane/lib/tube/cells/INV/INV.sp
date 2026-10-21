* INV — inversor a válvula termiônica (1 válvula JAN-6418 + resistor de placa + resistor de grade)
.subckt INV A Y VDD GND
RL VDD Y  10k
R1 A   g1 47k
V1 Y   g1 GND TUBE
.ends INV
