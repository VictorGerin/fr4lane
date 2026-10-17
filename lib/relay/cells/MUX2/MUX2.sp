* MUX2 — multiplexador: o contato de S comuta a saída entre A (solto) e B (energizado)
* K<nome> bobina+ bobina- comum NA NF RELAY; D<nome> anodo catodo DIODE (supressão)
.subckt MUX2 A B S Y VDD GND
K1 S GND Y B A RELAY
D1 GND S DIODE
.ends MUX2
