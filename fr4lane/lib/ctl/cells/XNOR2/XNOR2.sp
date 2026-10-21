* XNOR2 — XNOR de 2 entradas CTL (NOR2 + AND2 por coincidência de corrente + NOR2 + INV)
* Com entradas isoladas em cada núcleo, XNOR2 opera com qualquer combinação de fan-out
* nas entradas A e B sem desbalanceamento de corrente de inibição.
.subckt XNOR2 A B Y VDD GND
X1 A  B  ab VDD GND AND2
X2 A  B  no VDD GND NOR2
X3 ab no xn VDD GND NOR2
X4 xn Y     VDD GND INV
.ends XNOR2
