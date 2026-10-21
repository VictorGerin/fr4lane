* AND2 — porta E DTL (NAND2 + INV; 2 transistores NPN)
.subckt AND2 A B Y VDD GND
X1 A B n VDD GND NAND2
X2 n Y   VDD GND INV
.ends AND2
