* INV — inversor: o contato liga a saída ao GND (energizado) ou ao VDD
* K<nome> bobina+ bobina- comum NA NF RELAY; D<nome> anodo catodo DIODE (supressão)
.subckt INV A Y VDD GND
K1 A GND Y GND VDD RELAY
D1 GND A DIODE
.ends INV
