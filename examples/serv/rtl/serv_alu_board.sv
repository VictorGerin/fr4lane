// serv_alu_board.sv : Placa de ALU e Registradores Temporários do SERV em SystemVerilog
//
// Agrupa os elementos de processamento aritmético e deslocamento:
//   - serv_alu     : ALU bit-serial de 1 bit (macro independente de alta densidade)
//   - serv_bufreg  : Buffer registrador de deslocamento 1 e gerador de endereço de dados
//   - serv_bufreg2 : Buffer registrador de deslocamento 2 e gerador/receptor de dados
module serv_alu_board (
   input  logic        clk,
   // Temporização serial
   input  logic        i_cnt_en,
   input  logic        i_cnt0,
   input  logic        i_cnt1,
   input  logic        i_cnt7,
   input  logic        i_cnt_done,
   input  logic        i_init,
   // Controle da ALU
   input  logic        i_alu_sub,
   input  logic [1:0]  i_alu_bool_op,
   input  logic        i_alu_cmp_eq,
   input  logic        i_alu_cmp_sig,
   input  logic [2:0]  i_alu_rd_sel,
   // Controle dos buffers e deslocador
   input  logic        i_bufreg_en,
   input  logic        i_bufreg_rs1_en,
   input  logic        i_bufreg_imm_en,
   input  logic        i_bufreg_clr_lsb,
   input  logic        i_bufreg_sh_signed,
   input  logic        i_op_b_sel,
   input  logic        i_shift_op,
   input  logic        i_sh_right,
   // Entradas seriais de dados
   input  logic        i_rs1,
   input  logic        i_rs2,
   input  logic        i_imm,
   input  logic [1:0]  i_mem_bytecnt,
   // Saídas seriais e de feedback
   output logic        o_alu_rd,
   output logic        o_alu_cmp,
   output logic        o_sh_done,
   output logic [1:0]  o_lsb,
   output logic        o_bufreg_q,
   output logic        o_bufreg2_q,
   // Barramento de dados (Wishbone)
   output logic [31:0] o_dbus_adr,
   output logic [31:0] o_dbus_dat,
   input  logic [31:0] i_dbus_rdt,
   input  logic        i_dbus_ack
);

   logic op_b;
   logic [1:0] lsb_internal;

   assign o_lsb = lsb_internal;

   serv_alu alu (
      .clk       (clk),
      .i_en      (i_cnt_en),
      .i_cnt0    (i_cnt0),
      .o_cmp     (o_alu_cmp),
      .i_sub     (i_alu_sub),
      .i_bool_op (i_alu_bool_op),
      .i_cmp_eq  (i_alu_cmp_eq),
      .i_cmp_sig (i_alu_cmp_sig),
      .i_rd_sel  (i_alu_rd_sel),
      .i_rs1     (i_rs1),
      .i_op_b    (op_b),
      .i_buf     (o_bufreg_q),
      .o_rd      (o_alu_rd)
   );

   serv_bufreg bufreg (
      .i_clk            (clk),
      .i_cnt0           (i_cnt0),
      .i_cnt1           (i_cnt1),
      .i_cnt_done       (i_cnt_done),
      .i_en             (i_bufreg_en),
      .i_init           (i_init),
      .o_lsb            (lsb_internal),
      .i_sh_signed      (i_bufreg_sh_signed),
      .i_rs1_en         (i_bufreg_rs1_en),
      .i_imm_en         (i_bufreg_imm_en),
      .i_clr_lsb        (i_bufreg_clr_lsb),
      .i_shift_op       (i_shift_op),
      .i_right_shift_op (i_sh_right),
      .i_shamt          (o_dbus_dat[26:24]),
      .i_rs1            (i_rs1),
      .i_imm            (i_imm),
      .o_q              (o_bufreg_q),
      .o_dbus_adr       (o_dbus_adr)
   );

   serv_bufreg2 bufreg2 (
      .i_clk      (clk),
      .i_en       (i_cnt_en),
      .i_init     (i_init),
      .i_cnt7     (i_cnt7),
      .i_cnt_done (i_cnt_done),
      .i_sh_right (i_sh_right),
      .i_lsb      (lsb_internal),
      .i_bytecnt  (i_mem_bytecnt),
      .o_sh_done  (o_sh_done),
      .i_op_b_sel (i_op_b_sel),
      .i_shift_op (i_shift_op),
      .i_rs2      (i_rs2),
      .i_imm      (i_imm),
      .o_op_b     (op_b),
      .o_q        (o_bufreg2_q),
      .o_dat      (o_dbus_dat),
      .i_load     (i_dbus_ack),
      .i_dat      (i_dbus_rdt)
   );

endmodule
