* DFFR — flip-flop D, borda de subida, clear assíncrono ativo baixo (estilo 7474 em DTL; 2 NAND2 + 4 NAND3 = 6 NPNs)
.subckt DFFR D C R Q VDD GND
X1 n4 n2 n1     VDD GND NAND2
X2 n1 R  C  n2  VDD GND NAND3
X3 n2 C  n4 n3  VDD GND NAND3
X4 n3 R  D  n4  VDD GND NAND3
X5 n2 QN Q      VDD GND NAND2
X6 Q  R  n3 QN  VDD GND NAND3
.ends DFFR
