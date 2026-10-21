* XNOR2 — XNOR: K1 gera !A; K2 escolhe A (B energizado) ou !A
* K<nome> bobina+ bobina- comum NA NF RELAY; D<nome> anodo catodo DIODE (supressão)
.subckt XNOR2 A B Y VDD GND
K1 A GND n GND VDD RELAY
K2 B GND Y A n RELAY
D1 GND A DIODE
D2 GND B DIODE
.ends XNOR2
