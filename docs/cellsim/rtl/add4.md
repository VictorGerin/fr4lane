# Circuito `add4` na família `rtl` (ngspice)

36 células, 204 componentes, 512 vetores (todas as combinações das entradas, simuladas em lotes de 64). Cada vetor é conferido contra a lógica do netlist; o caminho crítico é o último cruzamento de uma saída depois da mudança das entradas. O netlist publicado tem os primeiros 64 vetores.

| Canto | Resultado | Sem convergir | Caminho crítico |
|---|---|---:|---|
| típico | OK | — | 1.76 µs (s[3] no vetor 53) |
| lento | OK | — | 1.86 µs (s[3] no vetor 53) |
| rápido | OK | — | 1.89 µs (s[3] no vetor 53) |
| quente | OK | — | 1.91 µs (s[3] no vetor 53) |

Dados completos de todos os vetores e cantos em [add4.csv](add4.csv). Reproduzir (canto típico): `ngspice -b add4.cir`

![add4](add4.png)

