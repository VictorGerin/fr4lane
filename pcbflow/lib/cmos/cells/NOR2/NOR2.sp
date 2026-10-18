* NOR2 — NOR de 2 entradas, CMOS estático
* M<nome> dreno gate fonte corpo modelo (corpo = fonte: MOSFET discreto)
.subckt NOR2 A B Y VDD GND
MP1 p1 A VDD VDD PMOS
MP2 Y  B p1  p1  PMOS
MN1 Y  A GND GND NMOS
MN2 Y  B GND GND NMOS
.ends NOR2
