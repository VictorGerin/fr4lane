* DLAT — latch D transparente com E = 1: K1 liga a bobina de K2 a D (E energizado) ou à própria saída (E solto), e K2 se autotrava
* K<nome> bobina+ bobina- comum NA NF RELAY; D<nome> anodo catodo DIODE (supressão)
.subckt DLAT D E Q VDD GND
K1 E GND x D Q RELAY
K2 x GND Q VDD GND RELAY
D1 GND E DIODE
D2 GND x DIODE
.ends DLAT
