* AND2_X2 — AND de 2 entradas com 2 saídas (NAND2 + 2 inversores), fan-out 10–20
* Cada inversor é uma saída e alimenta até 10 entradas; o sizing divide as
* cargas entre Y0 e Y1.
.subckt AND2_X2 A B Y0 Y1 VDD GND
X1 A B n  VDD GND NAND2
X2 n   Y0 VDD GND INV
X3 n   Y1 VDD GND INV
.ends AND2_X2
