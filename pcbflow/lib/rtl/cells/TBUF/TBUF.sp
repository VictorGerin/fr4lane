* TBUF — driver de barramento de coletor aberto (como o 74LS03)
* Com E = 1 e A = 0, Q1 e Q2 conduzem e puxam Y para 0. Com A = 1 ou E = 0, Y
* fica solto e o pull-up do barramento (PULLUP) o leva a 1. Não há resistor de
* coletor em Y: várias saídas dividem a mesma linha (wired-AND).
.subckt TBUF A E Y VDD GND
RLI VDD an 1k
RI  A   bi 10k
QI  an  bi GND NPN
R1  E   b1 10k
R2  an  b2 10k
Q1  Y   b1 n1  NPN
Q2  n1  b2 GND NPN
.ends TBUF
