* INV — inversor CMOS
* M<nome> dreno gate fonte corpo modelo (corpo = fonte: MOSFET discreto)
.subckt INV A Y VDD GND
MP1 Y A VDD VDD PMOS
MN1 Y A GND GND NMOS
.ends INV
