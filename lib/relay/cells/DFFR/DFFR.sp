* DFFR — flip-flop D, borda de subida, clear assíncrono ativo baixo: como o DFF, com K5/K6 cortando as bobinas do mestre e do escravo enquanto R = 0
* K<nome> bobina+ bobina- comum NA NF RELAY; D<nome> anodo catodo DIODE (supressão)
.subckt DFFR D C R Q VDD GND
K1 C GND X1 Q1 D RELAY
K5 R GND Y1 X1 GND RELAY
K2 Y1 GND Q1 VDD GND RELAY
K3 C GND X2 Q1 Q RELAY
K6 R GND Y2 X2 GND RELAY
K4 Y2 GND Q VDD GND RELAY
D1 GND C DIODE
D2 GND R DIODE
D3 GND Y1 DIODE
D4 GND Y2 DIODE
.ends DFFR
