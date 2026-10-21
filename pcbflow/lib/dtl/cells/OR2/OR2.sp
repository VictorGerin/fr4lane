* OR2 — porta OU DTL (NOR2 + INV; 2 transistores NPN)
.subckt OR2 A B Y VDD GND
X1 A B n VDD GND NOR2
X2 n Y   VDD GND INV
.ends OR2
