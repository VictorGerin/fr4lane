* OR2 — OR: K1 gera A; K2 põe VDD (B energizado) ou passa A
* K<nome> bobina+ bobina- comum NA NF RELAY; D<nome> anodo catodo DIODE (supressão)
.subckt OR2 A B Y VDD GND
K1 A GND n VDD GND RELAY
K2 B GND Y VDD n RELAY
D1 GND A DIODE
D2 GND B DIODE
.ends OR2
