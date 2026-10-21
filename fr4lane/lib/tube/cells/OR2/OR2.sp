* OR2 — porta OU a válvulas termiônicas (NOR2 + INV; 3 válvulas)
.subckt OR2 A B Y VDD GND
X1 A B n VDD GND NOR2
X2 n Y   VDD GND INV
.ends OR2
