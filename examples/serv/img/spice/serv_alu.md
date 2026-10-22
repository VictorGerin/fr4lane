# Circuito `serv_alu` na família `rtl` (ngspice)

44 células, 291 componentes, 16 vetores (todas as combinações das entradas, simuladas em lotes de 64). Cada vetor é conferido contra a lógica do netlist; o caminho crítico é o último cruzamento de uma saída depois da mudança das entradas. O netlist publicado tem os primeiros 16 vetores.

| Canto | Resultado | Sem convergir | Caminho crítico |
|---|---|---:|---|
| típico | OK | — | 1.65 µs (o_cmp no vetor 9) |
| lento | OK | — | 1.59 µs (o_cmp no vetor 9) |
| rápido | OK | — | 1.83 µs (o_cmp no vetor 9) |
| quente | OK | — | 1.79 µs (o_cmp no vetor 9) |

Dados completos de todos os vetores e cantos em [serv_alu.csv](serv_alu.csv). Reproduzir (canto típico): `ngspice -b serv_alu.cir`

![serv_alu](serv_alu.png)

