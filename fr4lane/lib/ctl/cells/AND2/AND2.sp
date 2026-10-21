* AND2 — AND de 2 entradas CTL (NAND2 por coincidência de corrente + inversor)
.subckt AND2 A B Y VDD GND
X1 A B n  VDD GND NAND2
X2 n   Y  VDD GND INV
.ends AND2
