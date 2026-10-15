* AOI21 — AND-OR-INVERT: Y = !((A&B)|C)
* M<nome> dreno gate fonte corpo modelo (corpo = fonte: MOSFET discreto)
.subckt AOI21 A B C Y VDD GND
MP1 p1 A VDD VDD PMOS
MP2 p1 B VDD VDD PMOS
MP3 Y  C p1  p1  PMOS
MN1 Y  A n1  n1  NMOS
MN2 n1 B GND GND NMOS
MN3 Y  C GND GND NMOS
.ends AOI21
