* DLAT — latch D transparente com E = 1 (latch SR de 4 NAND2 DTL; apenas 4 transistores NPN)
* !R = NAND(!S, E) sem inverter D: !S = NAND(D, E)
.subckt DLAT D E Q VDD GND
X1 D  E  sb  VDD GND NAND2
X2 sb E  rb  VDD GND NAND2
X3 sb QN Q   VDD GND NAND2
X4 rb Q  QN  VDD GND NAND2
.ends DLAT
