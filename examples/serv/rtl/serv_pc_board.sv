// serv_pc_board.sv : Placa do Program Counter (PC) do SERV em SystemVerilog
//
// Agrupa a gestão e avanço serial do PC e cálculo de saltos/branches:
//   - serv_ctrl : Somador e registrador de deslocamento do PC (largura parametrizável PC_WIDTH)
module serv_pc_board #(
   parameter int        PC_WIDTH = 32,
   parameter bit [31:0] RESET_PC = 32'd0
) (
   input  logic        clk,
   input  logic        i_rst,
   // Temporização e controle vindos da serv_ctrl_board
   input  logic        i_pc_en,
   input  logic        i_cnt12to31,
   input  logic        i_cnt0,
   input  logic        i_cnt1,
   input  logic        i_cnt2,
   input  logic        i_jump,
   input  logic        i_jal_or_jalr,
   input  logic        i_utype,
   input  logic        i_pc_rel,
   // Dados seriais
   input  logic        i_imm,
   input  logic        i_bufreg_q,
   // Saída serial de PC para link/AUIPC (escrito no RF)
   output logic        o_ctrl_rd,
   output logic        o_bad_pc,
   // Barramento de endereço de instrução (Wishbone)
   output logic [31:0] o_ibus_adr
);

   serv_ctrl #(
      .PC_WIDTH (PC_WIDTH),
      .RESET_PC (RESET_PC)
   ) ctrl (
      .clk           (clk),
      .i_rst         (i_rst),
      .i_pc_en       (i_pc_en),
      .i_cnt12to31   (i_cnt12to31),
      .i_cnt0        (i_cnt0),
      .i_cnt1        (i_cnt1),
      .i_cnt2        (i_cnt2),
      .i_jump        (i_jump),
      .i_jal_or_jalr (i_jal_or_jalr),
      .i_utype       (i_utype),
      .i_pc_rel      (i_pc_rel),
      .i_imm         (i_imm),
      .i_buf         (i_bufreg_q),
      .o_rd          (o_ctrl_rd),
      .o_bad_pc      (o_bad_pc),
      .o_ibus_adr    (o_ibus_adr)
   );

endmodule
