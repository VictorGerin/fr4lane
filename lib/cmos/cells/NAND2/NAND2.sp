* NAND2 — NAND de 2 entradas, CMOS estático
* M<nome> dreno gate fonte corpo modelo (corpo = fonte: MOSFET discreto)
.subckt NAND2 A B Y VDD GND
MP1 Y  A VDD VDD PMOS
MP2 Y  B VDD VDD PMOS
MN1 Y  A n1  n1  NMOS
MN2 n1 B GND GND NMOS
.ends NAND2
