* NAND3 — NAND de 3 entradas, CMOS estático
* M<nome> dreno gate fonte corpo modelo (corpo = fonte: MOSFET discreto)
.subckt NAND3 A B C Y VDD GND
MP1 Y  A VDD VDD PMOS
MP2 Y  B VDD VDD PMOS
MP3 Y  C VDD VDD PMOS
MN1 Y  A n1  n1  NMOS
MN2 n1 B n2  n2  NMOS
MN3 n2 C GND GND NMOS
.ends NAND3
