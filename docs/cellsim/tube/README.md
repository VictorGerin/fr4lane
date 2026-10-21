# Células da família `tube` no ngspice

Cada célula da família é simulada como circuito de verdade, com o modelo SPICE dos componentes, e não só como chaves ideais. Os resultados de todos os cantos estão em [resultados.md](resultados.md).

## Reproduzir

Cada `<CÉLULA>.cir` é um netlist do ngspice completo: o modelo do transistor, os subcircuitos da célula e da carga, as fontes com os vetores de teste e as medidas. O cabeçalho explica os vetores e o valor esperado de cada medida. É o teste funcional no canto típico.

```sh
ngspice -b AND2.cir      # imprime as medidas e grava AND2.dat com as formas de onda
```

Para rodar todos os cantos e refazer estes arquivos: `fr4lane-cellsim --lib tube --export docs/cellsim/tube`.

## Células

### AND2

E de 2 entradas a válvulas termiônicas (NAND2 + INV; 3 válvulas)

[AND2.cir](AND2.cir) — passa no canto típico

![AND2](AND2.png)

### BUF

buffer a válvulas termiônicas (2 inversores; 2 válvulas JAN-6418)

[BUF.cir](BUF.cir) — passa no canto típico

![BUF](BUF.png)

### DFF

flip-flop D de borda de subida a válvulas termiônicas (5 NOR2 + 1 NOR3 + 1 INV; 14 válvulas JAN-6418)

[DFF.cir](DFF.cir) — passa no canto típico

![DFF](DFF.png)

### DFFR

flip-flop D com clear ativo baixo a válvulas termiônicas (3 NOR2 + 3 NOR3 + 2 INV; 17 válvulas JAN-6418)

[DFFR.cir](DFFR.cir) — passa no canto típico

![DFFR](DFFR.png)

### DLAT

latch D transparente a válvulas termiônicas (4 NOR2 + 1 INV; 9 válvulas JAN-6418)

[DLAT.cir](DLAT.cir) — passa no canto típico

![DLAT](DLAT.png)

### INV

inversor a válvula termiônica (1 válvula JAN-6418 + 2 resistores)

[INV.cir](INV.cir) — passa no canto típico

![INV](INV.png)

### NAND2

NAND de 2 entradas a válvulas termiônicas (2 válvulas JAN-6418 em série + 3 resistores)

[NAND2.cir](NAND2.cir) — passa no canto típico

![NAND2](NAND2.png)

### NOR2

NOR de 2 entradas a válvulas termiônicas (2 válvulas JAN-6418 em paralelo + 3 resistores)

[NOR2.cir](NOR2.cir) — passa no canto típico

![NOR2](NOR2.png)

### NOR3

NOR de 3 entradas a válvulas termiônicas (3 válvulas JAN-6418 em paralelo + 4 resistores)

[NOR3.cir](NOR3.cir) — passa no canto típico

![NOR3](NOR3.png)

### OR2

OU de 2 entradas a válvulas termiônicas (NOR2 + INV; 3 válvulas)

[OR2.cir](OR2.cir) — passa no canto típico

![OR2](OR2.png)

### XNOR2

XNOR de 2 entradas a válvulas termiônicas (4 NOR2; 8 válvulas JAN-6418)

[XNOR2.cir](XNOR2.cir) — passa no canto típico

![XNOR2](XNOR2.png)

### XOR2

XOR de 2 entradas a válvulas termiônicas (4 NAND2; 8 válvulas JAN-6418)

[XOR2.cir](XOR2.cir) — passa no canto típico

![XOR2](XOR2.png)

## Circuito tanque

Um circuito inteiro, sintetizado pelo fr4lane: 19 células, 188 componentes e 17 vetores. Resultados e gráfico em [tanque.md](tanque.md); dados em [tanque.csv](tanque.csv); netlist em [tanque.cir](tanque.cir).

