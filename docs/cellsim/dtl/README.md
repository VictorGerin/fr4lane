# Células da família `dtl` no ngspice

Cada célula da família é simulada como circuito de verdade, com o modelo SPICE dos componentes, e não só como chaves ideais. Os resultados de todos os cantos estão em [resultados.md](resultados.md).

## Reproduzir

Cada `<CÉLULA>.cir` é um netlist do ngspice completo: o modelo do transistor, os subcircuitos da célula e da carga, as fontes com os vetores de teste e as medidas. O cabeçalho explica os vetores e o valor esperado de cada medida. É o teste funcional no canto típico.

```sh
ngspice -b AND2.cir      # imprime as medidas e grava AND2.dat com as formas de onda
```

Para rodar todos os cantos e refazer estes arquivos: `fr4lane-cellsim --lib dtl --export docs/cellsim/dtl`.

## Células

### AND2

E de 2 entradas DTL (NAND2 + INV; 2 transistores NPN)

[AND2.cir](AND2.cir) — passa no canto típico

![AND2](AND2.png)

### BUF

buffer DTL (2 inversores em cascata; 2 transistores NPN)

[BUF.cir](BUF.cir) — passa no canto típico

![BUF](BUF.png)

### DFF

flip-flop D de borda de subida DTL (5 NAND2 + 1 NAND3; 6 transistores NPN)

[DFF.cir](DFF.cir) — passa no canto típico

![DFF](DFF.png)

### DFFR

flip-flop D com clear ativo baixo DTL (2 NAND2 + 4 NAND3; 6 transistores NPN)

[DFFR.cir](DFFR.cir) — passa no canto típico

![DFFR](DFFR.png)

### DLAT

latch D transparente DTL (4 NAND2; 4 transistores NPN)

[DLAT.cir](DLAT.cir) — passa no canto típico

![DLAT](DLAT.png)

### INV

inversor DTL com deslocamento de nível por 2 diodos (1 NPN + 3 diodos + 3 resistores)

[INV.cir](INV.cir) — passa no canto típico

![INV](INV.png)

### NAND2

NAND de 2 entradas DTL em um único transistor (1 NPN + 4 diodos + 3 resistores)

[NAND2.cir](NAND2.cir) — passa no canto típico

![NAND2](NAND2.png)

### NAND3

NAND de 3 entradas DTL em um único transistor (1 NPN + 5 diodos + 3 resistores)

[NAND3.cir](NAND3.cir) — passa no canto típico

![NAND3](NAND3.png)

### NOR2

NOR de 2 entradas DTL em um único transistor (1 NPN + 2 diodos + 4 resistores)

[NOR2.cir](NOR2.cir) — passa no canto típico

![NOR2](NOR2.png)

### NOR3

NOR de 3 entradas DTL em um único transistor (1 NPN + 3 diodos + 5 resistores)

[NOR3.cir](NOR3.cir) — passa no canto típico

![NOR3](NOR3.png)

### OR2

OU de 2 entradas DTL (NOR2 + INV; 2 transistores NPN)

[OR2.cir](OR2.cir) — passa no canto típico

![OR2](OR2.png)

### XNOR2

XNOR de 2 entradas DTL (XOR2 + INV; 5 transistores NPN)

[XNOR2.cir](XNOR2.cir) — passa no canto típico

![XNOR2](XNOR2.png)

### XOR2

XOR de 2 entradas DTL (4 NAND2; 4 transistores NPN)

[XOR2.cir](XOR2.cir) — passa no canto típico

![XOR2](XOR2.png)

## Circuito tanque

Um circuito inteiro, sintetizado pelo fr4lane: 18 células, 292 componentes e 17 vetores. Resultados e gráfico em [tanque.md](tanque.md); dados em [tanque.csv](tanque.csv); netlist em [tanque.cir](tanque.cir).

