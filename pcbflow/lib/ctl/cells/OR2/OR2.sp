* OR2 — OR de 2 entradas CTL (NOR2 + inversor)
.subckt OR2 A B Y VDD GND
X1 A B n  VDD GND NOR2
X2 n   Y  VDD GND INV
.ends OR2
