* NOR3 — NOR de 3 entradas, CMOS estático
* M<nome> dreno gate fonte corpo modelo (corpo = fonte: MOSFET discreto)
.subckt NOR3 A B C Y VDD GND
MP1 p1 A VDD VDD PMOS
MP2 p2 B p1  p1  PMOS
MP3 Y  C p2  p2  PMOS
MN1 Y  A GND GND NMOS
MN2 Y  B GND GND NMOS
MN3 Y  C GND GND NMOS
.ends NOR3
