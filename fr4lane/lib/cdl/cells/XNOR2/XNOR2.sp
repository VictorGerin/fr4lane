* XNOR2 — coincidência CDL de 2 entradas em 3 núcleos: (A & B) | !(A | B)
.subckt XNOR2 A B Y VDD GND
X1 A  B  ab VDD GND AND2
X2 A  B  nr VDD GND NOR2
X3 ab nr Y  VDD GND OR2
.ends XNOR2
