* NAND2 — porta NAND CDL (AND2 por coincidência de corrente + inversor por inibição magnética)
.subckt NAND2 A B Y VDD GND
X1 A B m VDD GND AND2
X2 m Y VDD GND INV
.ends NAND2
