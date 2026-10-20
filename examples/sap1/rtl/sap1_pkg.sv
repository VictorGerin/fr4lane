// Tipos e constantes do SAP-1, compartilhados pelos módulos.
//
// Limites das ferramentas que este código respeita (Yosys 0.66, Icarus 13):
// - o Yosys não aceita "import" no cabeçalho nem no corpo de um módulo, só no
//   escopo do arquivo, e mesmo assim só para constantes e rótulos de enum:
//   os tipos são sempre qualificados (sap1_pkg::ctrl_t);
// - o Icarus cai ao compilar um always_comb que lê campo de struct: quem lê a
//   palavra de controle usa assign ou recebe os campos já separados nas portas.
package sap1_pkg;
    localparam int DW    = 8;          // largura de dados e do barramento
    localparam int AW    = 4;          // largura de endereço
    localparam int DEPTH = 1 << AW;    // bytes de RAM

    // Instrução: opcode nos 4 bits de cima, endereço ou imediato nos 4 de baixo.
    typedef enum logic [3:0] {
        NOP = 4'b0000,  // nada
        LDA = 4'b0001,  // A = RAM[a]
        ADD = 4'b0010,  // A = A + RAM[a]        (atualiza as flags)
        SUB = 4'b0011,  // A = A - RAM[a]        (atualiza as flags)
        STA = 4'b0100,  // RAM[a] = A
        LDI = 4'b0101,  // A = n
        JMP = 4'b0110,  // PC = a
        JC  = 4'b0111,  // se carry, PC = a
        JZ  = 4'b1000,  // se zero, PC = a
        OUT = 4'b1110,  // saída = A
        HLT = 4'b1111   // para
    } opcode_t;

    // Passos de cada instrução: T0 e T1 buscam, T2 a T4 executam.
    typedef enum logic [2:0] {T0, T1, T2, T3, T4} step_t;

    // Palavra de controle, com os nomes do Ben Eater.
    typedef struct packed {
        logic hlt;  // para o contador de passos
        logic mi;   // carrega o endereço da memória
        logic ri;   // grava na RAM
        logic ro;   // RAM no barramento
        logic io;   // operando da instrução no barramento
        logic ii;   // carrega a instrução
        logic ai;   // carrega A
        logic ao;   // A no barramento
        logic eo;   // ALU no barramento
        logic su;   // ALU subtrai
        logic bi;   // carrega B
        logic oi;   // carrega a saída
        logic ce;   // incrementa o PC
        logic co;   // PC no barramento
        logic j;    // salta (carrega o PC)
        logic fi;   // carrega as flags
    } ctrl_t;
endpackage
