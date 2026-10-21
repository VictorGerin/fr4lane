* XOR2 — OU-exclusivo DTL clássico com 4 portas NAND2 (apenas 4 transistores NPN)
.subckt XOR2 A B Y VDD GND
X1 A  B  n1 VDD GND NAND2
X2 A  n1 n2 VDD GND NAND2
X3 B  n1 n3 VDD GND NAND2
X4 n2 n3 Y  VDD GND NAND2
.ends XOR2
