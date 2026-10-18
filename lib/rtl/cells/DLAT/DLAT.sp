* DLAT — latch D transparente com E = 1 (latch SR de NORs com entrada controlada; 4 NORs + inversor)
* S = D·E sai de NOR(R, !E) sem inverter D: R = NOR(D, !E) = !D·E
.subckt DLAT D E Q VDD GND
X0 E  eb     VDD GND INV
X1 D  eb r   VDD GND NOR2
X2 r  eb s   VDD GND NOR2
X3 r  QN Q   VDD GND NOR2
X4 s  Q  QN  VDD GND NOR2
.ends DLAT
