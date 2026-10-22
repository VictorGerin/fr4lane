// serv_core.sv : Topo da placa do SERV em SystemVerilog moderno
//
// Núcleo RISC-V RV32I bit-serial (arquitetura SERV) em SystemVerilog limpo,
// com tipos logic, sem CSRs e com banco de registradores em SRAM externa de 512 x 2 bits.
module serv_core (
   input  logic        clk,
   input  logic        i_rst,
   // Barramento de instrução (Wishbone)
   output logic [31:0] o_ibus_adr,
   output logic        o_ibus_cyc,
   input  logic [31:0] i_ibus_rdt,
   input  logic        i_ibus_ack,
   // Barramento de dados (Wishbone)
   output logic [31:0] o_dbus_adr,
   output logic [31:0] o_dbus_dat,
   output logic [3:0]  o_dbus_sel,
   output logic        o_dbus_we,
   output logic        o_dbus_cyc,
   input  logic [31:0] i_dbus_rdt,
   input  logic        i_dbus_ack,
   // SRAM externa do banco de registradores (512 x 2 bits)
   output logic [8:0]  o_rf_waddr,
   output logic [1:0]  o_rf_wdata,
   output logic        o_rf_wen,
   output logic [8:0]  o_rf_raddr,
   output logic        o_rf_ren,
   input  logic [1:0]  i_rf_rdata
);

   logic       rf_wreq;
   logic       rf_rreq;
   logic       rf_ready;
   logic [4:0] wreg0;
   logic [4:0] wreg1;
   logic [4:0] rreg0;
   logic [4:0] rreg1;
   logic       wen0;
   logic       wen1;
   logic       wdata0;
   logic       wdata1;
   logic       rdata0;
   logic       rdata1;

   serv_rf_ram_if #(
      .width    (2),
      .csr_regs (0),
      .raw      (5),
      .l2w      (1),
      .aw       (9)
   ) rf_ram_if (
      .i_clk    (clk),
      .i_rst    (i_rst),
      .i_wreq   (rf_wreq),
      .i_rreq   (rf_rreq),
      .o_ready  (rf_ready),
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

   serv_top #(
      .RESET_PC (32'd0)
   ) cpu (
      .clk        (clk),
      .i_rst      (i_rst),
      .o_rf_rreq  (rf_rreq),
      .o_rf_wreq  (rf_wreq),
      .i_rf_ready (rf_ready),
      .o_wreg0    (wreg0),
      .o_wreg1    (wreg1),
      .o_wen0     (wen0),
      .o_wen1     (wen1),
      .o_wdata0   (wdata0),
      .o_wdata1   (wdata1),
      .o_rreg0    (rreg0),
      .o_rreg1    (rreg1),
      .i_rdata0   (rdata0),
      .i_rdata1   (rdata1),
      .o_ibus_adr (o_ibus_adr),
      .o_ibus_cyc (o_ibus_cyc),
      .i_ibus_rdt (i_ibus_rdt),
      .i_ibus_ack (i_ibus_ack),
      .o_dbus_adr (o_dbus_adr),
      .o_dbus_dat (o_dbus_dat),
      .o_dbus_sel (o_dbus_sel),
      .o_dbus_we  (o_dbus_we),
      .o_dbus_cyc (o_dbus_cyc),
      .i_dbus_rdt (i_dbus_rdt),
      .i_dbus_ack (i_dbus_ack)
   );

endmodule
