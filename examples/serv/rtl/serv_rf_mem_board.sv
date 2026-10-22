// serv_rf_mem_board.sv : Placa do Banco de Registradores e Memória do SERV em SystemVerilog
//
// Agrupa a interface do banco de registradores e o alinhamento de memória:
//   - serv_rf_if     : Multiplexação e controle serial de leitura/escrita do RF (RV32I: 32 regs, RV32E: 16 regs)
//   - serv_rf_ram_if : Adaptador serial para SRAM síncrona 512x2 (RV32I) ou 256x2 (RV32E)
//   - serv_mem_if    : Alinhamento de dados e seleção de bytes (Wishbone SEL)
module serv_rf_mem_board #(
   parameter bit WITH_E = 1'b0,
   parameter int WREG   = WITH_E ? 4 : 5,
   parameter int AW     = WITH_E ? 8 : 9
) (
   input  logic            clk,
   input  logic            i_rst,
   // Temporização e controle vindos da serv_ctrl_board
   input  logic            i_cnt_en,
   input  logic [1:0]      i_bytecnt,
   input  logic [1:0]      i_lsb,
   // Handshake da SRAM de registradores
   input  logic            i_rf_rreq,
   input  logic            i_rf_wreq,
   output logic            o_rf_ready,
   // Endereçamento de registradores
   input  logic [WREG-1:0] i_rd_addr,
   input  logic [WREG-1:0] i_rs1_addr,
   input  logic [WREG-1:0] i_rs2_addr,
   input  logic            i_rd_en,
   // Seleção da fonte de dados para RD
   input  logic            i_ctrl_rd,
   input  logic            i_alu_rd,
   input  logic            i_rd_alu_en,
   input  logic            i_rd_mem_en,
   // Controle de acesso à memória (LOAD/STORE)
   input  logic            i_mem_signed,
   input  logic            i_mem_word,
   input  logic            i_mem_half,
   input  logic            i_bufreg2_q,
   // Saídas seriais para Datapath e FSM
   output logic            o_rs1,
   output logic            o_rs2,
   output logic            o_mem_misalign,
   // Barramento de dados (Wishbone byte enables)
   output logic [3:0]      o_dbus_sel,
   // Interface física com a SRAM externa do banco de registradores
   output logic [AW-1:0]   o_rf_waddr,
   output logic [1:0]      o_rf_wdata,
   output logic            o_rf_wen,
   output logic [AW-1:0]   o_rf_raddr,
   output logic            o_rf_ren,
   input  logic [1:0]      i_rf_rdata
);

   logic [WREG-1:0] wreg0;
   logic [WREG-1:0] wreg1;
   logic [WREG-1:0] rreg0;
   logic [WREG-1:0] rreg1;
   logic            wen0;
   logic            wen1;
   logic            wdata0;
   logic            wdata1;
   logic            rdata0;
   logic            rdata1;
   logic            mem_rd;

   serv_rf_ram_if #(
      .width    (2),
      .csr_regs (0),
      .raw      (WREG),
      .l2w      (1),
      .aw       (AW)
   ) rf_ram_if (
      .i_clk    (clk),
      .i_rst    (i_rst),
      .i_wreq   (i_rf_wreq),
      .i_rreq   (i_rf_rreq),
      .o_ready  (o_rf_ready),
      .i_wreg0  (wreg0),
      .i_wreg1  (wreg1),
      .i_wen0   (wen0),
      .i_wen1   (wen1),
      .i_wdata0 (wdata0),
      .i_wdata1 (wdata1),
      .i_rreg0  (rreg0),
      .i_rreg1  (rreg1),
      .o_rdata0 (rdata0),
      .o_rdata1 (rdata1),
      .o_waddr  (o_rf_waddr),
      .o_wdata  (o_rf_wdata),
      .o_wen    (o_rf_wen),
      .o_raddr  (o_rf_raddr),
      .o_ren    (o_rf_ren),
      .i_rdata  (i_rf_rdata)
   );

   serv_rf_if #(
      .WREG (WREG)
   ) rf_if (
      .i_cnt_en    (i_cnt_en),
      .o_wreg0     (wreg0),
      .o_wreg1     (wreg1),
      .o_wen0      (wen0),
      .o_wen1      (wen1),
      .o_wdata0    (wdata0),
      .o_wdata1    (wdata1),
      .o_rreg0     (rreg0),
      .o_rreg1     (rreg1),
      .i_rdata0    (rdata0),
      .i_rdata1    (rdata1),
      .i_rd_wen    (i_rd_en),
      .i_rd_waddr  (i_rd_addr),
      .i_ctrl_rd   (i_ctrl_rd),
      .i_alu_rd    (i_alu_rd),
      .i_rd_alu_en (i_rd_alu_en),
      .i_mem_rd    (mem_rd),
      .i_rd_mem_en (i_rd_mem_en),
      .i_rs1_raddr (i_rs1_addr),
      .o_rs1       (o_rs1),
      .i_rs2_raddr (i_rs2_addr),
      .o_rs2       (o_rs2)
   );

   serv_mem_if mem_if (
      .i_clk       (clk),
      .i_bytecnt   (i_bytecnt),
      .i_lsb       (i_lsb),
      .o_misalign  (o_mem_misalign),
      .i_signed    (i_mem_signed),
      .i_word      (i_mem_word),
      .i_half      (i_mem_half),
      .i_bufreg2_q (i_bufreg2_q),
      .o_rd        (mem_rd),
      .o_wb_sel    (o_dbus_sel)
   );

endmodule
