* OAI21 — OR-AND-INVERT: Y = !((A|B)&C)
* M<nome> dreno gate fonte corpo modelo (corpo = fonte: MOSFET discreto)
.subckt OAI21 A B C Y VDD GND
MP1 p1 A VDD VDD PMOS
MP2 Y  B p1  p1  PMOS
MP3 Y  C VDD VDD PMOS
MN1 n1 A GND GND NMOS
MN2 n1 B GND GND NMOS
MN3 Y  C n1  n1  NMOS
.ends OAI21
