* DFF — flip-flop D, borda de subida (6 NANDs)
* Sem portas de transmissão: o diodo de corpo do MOSFET discreto impede chave bidirecional.
.subckt DFF D C Q VDD GND
X1 n4 n2 n1     VDD GND NAND2
X2 n1 C  n2     VDD GND NAND2
X3 n2 C  n4 n3  VDD GND NAND3
X4 n3 D  n4     VDD GND NAND2
X5 n2 QN Q      VDD GND NAND2
X6 Q  n3 QN     VDD GND NAND2
.ends DFF
