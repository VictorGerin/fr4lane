* DFF — flip-flop D, borda de subida: mestre (transparente com C=0) e escravo (com C=1), cada um com um relé de seleção e um relé autotravado
* K<nome> bobina+ bobina- comum NA NF RELAY; D<nome> anodo catodo DIODE (supressão)
.subckt DFF D C Q VDD GND
K1 C GND X1 Q1 D RELAY
K2 X1 GND Q1 VDD GND RELAY
K3 C GND X2 Q1 Q RELAY
K4 X2 GND Q VDD GND RELAY
D1 GND C DIODE
D2 GND X1 DIODE
D3 GND X2 DIODE
.ends DFF
