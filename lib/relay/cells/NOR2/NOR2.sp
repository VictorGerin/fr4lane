* NOR2 — NOR: K1 gera !A; K2 põe GND (B energizado) ou passa !A
* K<nome> bobina+ bobina- comum NA NF RELAY; D<nome> anodo catodo DIODE (supressão)
.subckt NOR2 A B Y VDD GND
K1 A GND n GND VDD RELAY
K2 B GND Y GND n RELAY
D1 GND A DIODE
D2 GND B DIODE
.ends NOR2
