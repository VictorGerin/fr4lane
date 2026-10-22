// serv_pkg.sv : definições e constantes da arquitetura SERV em SystemVerilog
//
// Baseado no SERV (Olof Kindgren, licença ISC, veja LICENSE.serv).
package serv_pkg;

   // Opcodes base do RV32I (bits [6:2] da instrução)
   typedef enum logic [4:0] {
      OPCODE_LOAD      = 5'b00000,
      OPCODE_MISC_MEM  = 5'b00011,
      OPCODE_OP_IMM    = 5'b00100,
      OPCODE_AUIPC     = 5'b00101,
      OPCODE_STORE     = 5'b01000,
      OPCODE_OP        = 5'b01100,
      OPCODE_LUI       = 5'b01101,
      OPCODE_BRANCH    = 5'b11000,
      OPCODE_JALR      = 5'b11001,
      OPCODE_JAL       = 5'b11011,
      OPCODE_SYSTEM    = 5'b11100
   } opcode_t;

   // Operações booleanas da ALU
   typedef enum logic [1:0] {
      ALU_BOOL_XOR = 2'b00,
      ALU_BOOL_NONE= 2'b01,
      ALU_BOOL_OR  = 2'b10,
      ALU_BOOL_AND = 2'b11
   } alu_bool_t;

endpackage : serv_pkg
