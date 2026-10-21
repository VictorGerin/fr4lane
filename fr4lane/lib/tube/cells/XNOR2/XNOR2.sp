* XNOR2 — coincidência de 2 entradas a válvulas termiônicas (4 NOR2; 8 válvulas JAN-6418)
.subckt XNOR2 A B Y VDD GND
X1 A  B  n1 VDD GND NOR2
X2 A  n1 n2 VDD GND NOR2
X3 B  n1 n3 VDD GND NOR2
X4 n2 n3 Y  VDD GND NOR2
.ends XNOR2
