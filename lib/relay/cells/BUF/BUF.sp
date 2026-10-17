* BUF — buffer: o contato liga a saída ao VDD (energizado) ou ao GND
* K<nome> bobina+ bobina- comum NA NF RELAY; D<nome> anodo catodo DIODE (supressão)
.subckt BUF A Y VDD GND
K1 A GND Y VDD GND RELAY
D1 GND A DIODE
.ends BUF
