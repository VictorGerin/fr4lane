* XOR2 — XOR de 2 entradas CTL (NOR2 + AND2 por coincidência de corrente + NOR2)
* A^B = !( (A&B) | !(A|B) ): apenas 4 núcleos toroidais (1 NAND2, 1 INV, 2 NOR2).
.subckt XOR2 A B Y VDD GND
X1 A  B  ab VDD GND AND2
X2 A  B  no VDD GND NOR2
X3 ab no Y  VDD GND NOR2
.ends XOR2
