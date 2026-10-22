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

   // =========================================================================
   // Barramento do Sistema: Struct Aninhada unificando os 3 barramentos
   // =========================================================================
   typedef struct packed {
      ibus_req_t ibus;
      dbus_req_t dbus;
      rf_req_t   rf;
   } sys_req_t;

   typedef struct packed {
      ibus_rsp_t ibus;
      dbus_rsp_t dbus;
      rf_rsp_t   rf;
   } sys_rsp_t;

   // =========================================================================
   // Barramento de Empilhamento Inter-placas (J_STACK): Structs e Union Packed
   // =========================================================================
   // 1. Temporização e pulsos do ciclo serial
   typedef struct packed {
      logic init;
      logic cnt_en;
      logic cnt0;
      logic cnt1;
      logic cnt2;
      logic cnt3;
      logic cnt7;
      logic cnt11;
      logic cnt12;
      logic cnt0to3;
      logic cnt12to31;
      logic cnt_done;
   } stack_timing_t; // 12 bits

   // 2. Controle de FSM e fluxo
   typedef struct packed {
      logic pc_en;
      logic jump;
      logic jal_or_jalr;
      logic utype;
      logic pc_rel;
      logic mret;
      logic rd_en;
      logic rd_alu_en;
      logic rd_mem_en;
   } stack_ctrl_t; // 9 bits

   // 3. Controle da ALU
   typedef struct packed {
      logic       sub;
      logic [1:0] bool_op;
      logic       cmp_eq;
      logic       cmp_sig;
      logic [2:0] rd_sel;
      logic       op_b_sel;
      logic       shift_op;
      logic       sh_right;
   } stack_alu_ctrl_t; // 11 bits

   // 4. Controle dos registradores de buffer (bufreg)
   typedef struct packed {
      logic en;
      logic rs1_en;
      logic imm_en;
      logic clr_lsb;
      logic sh_signed;
   } stack_bufreg_ctrl_t; // 5 bits

   // 5. Controle de acesso e alinhamento de memória
   typedef struct packed {
      logic       signed_op;
      logic       word_op;
      logic       half_op;
      logic [1:0] bytecnt;
   } stack_mem_ctrl_t; // 5 bits

   // 6. Linhas seriais de dados entre placas (Datapath)
   typedef struct packed {
      logic       imm;
      logic       rs1;
      logic       rs2;
      logic       alu_rd;
      logic       ctrl_rd;
      logic       alu_cmp;
      logic       sh_done;
      logic       bufreg_q;
      logic       bufreg2_q;
      logic [1:0] lsb;
   } stack_datapath_t; // 11 bits

   // 7. Handshake e endereçamento de registradores
   typedef struct packed {
      logic [4:0] rd_addr;
      logic [4:0] rs1_addr;
      logic [4:0] rs2_addr;
      logic       rf_wreq;
      logic       rf_ready;
   } stack_rf_t; // 17 bits

   // Estrutura agrupada contendo todas as sub-structs do conector de pilha
   typedef struct packed {
      stack_timing_t      timing;  // 12 bits
      stack_ctrl_t        ctrl;    // 9 bits
      stack_alu_ctrl_t    alu;     // 11 bits
      stack_bufreg_ctrl_t bufreg;  // 5 bits
      stack_mem_ctrl_t    mem;     // 5 bits
      stack_datapath_t    data;    // 11 bits
      stack_rf_t          rf;      // 17 bits
   } stack_signals_t; // Total: 70 bits

   // Union Packed: permite acesso nomeado campo a campo OU acesso aos pinos brutos da PCB
   typedef union packed {
      stack_signals_t signals;
      logic [69:0]    raw_pins;
   } j_stack_t;

   // =========================================================================
   // Formatos de Instrução RISC-V: Union Packed com Structs
   // =========================================================================
   typedef union packed {
      logic [31:0] raw;
      struct packed {
         logic [6:0] funct7;
         logic [4:0] rs2;
         logic [4:0] rs1;
         logic [2:0] funct3;
         logic [4:0] rd;
         logic [6:0] opcode;
      } r;
      struct packed {
         logic [11:0] imm;
         logic [4:0]  rs1;
         logic [2:0]  funct3;
         logic [4:0]  rd;
         logic [6:0]  opcode;
      } i;
      struct packed {
         logic [6:0] imm_hi;
         logic [4:0] rs2;
         logic [4:0] rs1;
         logic [2:0] funct3;
         logic [4:0] imm_lo;
         logic [6:0] opcode;
      } s;
      struct packed {
         logic       imm_12;
         logic [5:0] imm_10_5;
         logic [4:0] rs2;
         logic [4:0] rs1;
         logic [2:0] funct3;
         logic [3:0] imm_4_1;
         logic       imm_11;
         logic [6:0] opcode;
      } b;
      struct packed {
         logic [19:0] imm;
         logic [4:0]  rd;
         logic [6:0]  opcode;
      } u;
      struct packed {
         logic       imm_20;
         logic [9:0] imm_10_1;
         logic       imm_11;
         logic [7:0] imm_19_12;
         logic [4:0] rd;
         logic [6:0] opcode;
      } j;
   } riscv_inst_t;

endpackage : serv_pkg
