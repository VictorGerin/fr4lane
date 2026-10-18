* INV — inversor RTL (1 NPN + 2 resistores)
* Q<nome> coletor base emissor modelo
* RL = resistor de coletor (pull-up), R1..R3 = resistores de base
.subckt INV A Y VDD GND
RL VDD Y  1k
R1 A   b1 10k
Q1 Y   b1 GND NPN
.ends INV
