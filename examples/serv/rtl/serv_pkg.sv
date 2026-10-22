// serv_pkg.sv : definições e constantes da arquitetura SERV em SystemVerilog
//
// Baseado no SERV (Olof Kindgren, licença ISC, veja LICENSE.serv).
package serv_pkg;

   // Opcodes base do RV32I / RV32E (bits [6:2] da instrução)
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

   // =========================================================================
   // Barramento 1: Instruções (ibus) - Leitura de Código / ROM / Flash
   // =========================================================================
   typedef struct packed {
      logic [31:0] adr;
      logic        cyc;
   } ibus_req_t;

   typedef struct packed {
      logic [31:0] rdt;
      logic        ack;
   } ibus_rsp_t;

   // =========================================================================
   // Barramento 2: Dados (dbus) - Wishbone para RAM e Periféricos MMIO
   // =========================================================================
   typedef struct packed {
      logic [31:0] adr;
      logic [31:0] dat;
      logic [3:0]  sel;
      logic        we;
      logic        cyc;
   } dbus_req_t;

   typedef struct packed {
      logic [31:0] rdt;
      logic        ack;
   } dbus_rsp_t;

   // =========================================================================
   // Barramento 3: Register File (rf) - Interface da SRAM externa de registradores
   // =========================================================================
   typedef struct packed {
      logic [8:0] waddr; // 9 bits (RV32I: 512 posições) ou 8 bits (RV32E: 256 posições com bit 8=0)
      logic [1:0] wdata;
      logic       wen;
      logic [8:0] raddr;
      logic       ren;
   } rf_req_t;

   typedef struct packed {
      logic [1:0] rdata;
   } rf_rsp_t;

endpackage : serv_pkg
