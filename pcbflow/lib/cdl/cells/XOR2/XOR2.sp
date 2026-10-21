* XOR2 — OU-exclusivo CDL de 2 entradas em 4 núcleos: (A | B) & !(A & B)
.subckt XOR2 A B Y VDD GND
X1 A B o VDD GND OR2
X2 A B n VDD GND NAND2
X3 o n Y VDD GND AND2
.ends XOR2
