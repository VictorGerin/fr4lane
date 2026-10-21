* DFF — flip-flop D, borda de subida (6 NORs CDL + inversor de clock; 7 núcleos)
* Dual do flip-flop de 6 NANDs: com NORs ele captura na borda de DESCIDA,
* por isso o clock passa por um inversor interno (ck = !C).
.subckt DFF D C Q VDD GND
X0 C  ck        VDD GND INV
X1 n4 n2 n1     VDD GND NOR2
X2 n1 ck n2     VDD GND NOR2
X3 n2 ck n4 n3  VDD GND NOR3
X4 n3 D  n4     VDD GND NOR2
X5 n2 QN Q      VDD GND NOR2
X6 Q  n3 QN     VDD GND NOR2
.ends DFF
