* AND2 — AND: K1 gera A; K2 passa A (B energizado) ou põe GND
* K<nome> bobina+ bobina- comum NA NF RELAY; D<nome> anodo catodo DIODE (supressão)
.subckt AND2 A B Y VDD GND
K1 A GND n VDD GND RELAY
K2 B GND Y n GND RELAY
D1 GND A DIODE
D2 GND B DIODE
.ends AND2
