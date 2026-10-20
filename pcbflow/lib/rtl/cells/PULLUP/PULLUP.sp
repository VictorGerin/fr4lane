* PULLUP — pull-up de uma linha de barramento: leva a linha a 1 quando nenhum
* driver (TBUF) a puxa para 0. Mesmo valor do resistor de coletor das portas.
.subckt PULLUP Y VDD GND
R1 VDD Y 1k
.ends PULLUP
