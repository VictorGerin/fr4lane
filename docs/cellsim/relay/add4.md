# Circuito `add4` na família `relay` (ngspice)

20 células, 80 componentes, 512 vetores (todas as combinações das entradas, simuladas em lotes de 8). Cada vetor é conferido contra a lógica do netlist; o caminho crítico é o último cruzamento de uma saída depois da mudança das entradas. O netlist publicado tem os primeiros 8 vetores.

| Canto | Resultado | Sem convergir | Caminho crítico |
|---|---|---:|---|
| típico | OK | 14 % | 45.2 ms (co no vetor 238) |
| lento | OK | 5 % | 45.2 ms (co no vetor 238) |
| quente | OK | 5 % | 45.2 ms (co no vetor 450) |
| rápido | OK | 9 % | 45.2 ms (co no vetor 238) |

Dados completos de todos os vetores e cantos em [add4.csv](add4.csv). Reproduzir (canto típico): `ngspice -b add4.cir`

![add4](add4.png)

