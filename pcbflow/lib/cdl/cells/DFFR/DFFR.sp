* DFFR — flip-flop D, borda de subida, clear assíncrono ativo baixo (lógica CDL; 8 núcleos)
* Dual do 7474 com portas NOR2/NOR3 de núcleos toroidais de ferrite e diodos 1N4148;
* o reset invertido é rn (SPICE não diferencia maiúsculas de minúsculas).
.subckt DFFR D C R Q VDD GND
X0 C  ck           VDD GND INV
X9 R  rn           VDD GND INV
X1 rn n4 n2 n1     VDD GND NOR3
X2 n1 ck n2        VDD GND NOR2
X3 n2 ck n4 n3     VDD GND NOR3
X4 n3 D  n4        VDD GND NOR2
X5 rn n2 QN Q      VDD GND NOR3
X6 Q  n3 QN        VDD GND NOR2
.ends DFFR
