// tb_serv_system.v : testbench do sistema multi-placa do SERV na pilha do fr4lane
//
// Modela fora da placa a memória de programa/dados (Wishbone, ack em 1 ciclo)
// e a SRAM de 512 x 2 bits do banco de registradores, e roda o programa que
// calcula 40 + 2 = 42 e grava o resultado no endereço 0x100:
//
//   0x00  addi x1, x0, 40      # x1 = 40
//   0x04  addi x2, x0, 2       # x2 = 2
//   0x08  add  x1, x1, x2      # x1 = 40 + 2 = 42
//   0x0c  sw   x1, 256(x0)     # mem[0x100] = 42
//   0x10  jal  x0, 0           # halt
`timescale 1ns/1ps
module tb_serv_system;
   reg clk = 1'b0;
   reg rst = 1'b1;
   always #50 clk = ~clk;

   wire [31:0] ibus_adr, dbus_adr, dbus_dat;
   wire        ibus_cyc, dbus_cyc, dbus_we;
   wire [3:0]  dbus_sel;
   reg [31:0]  ibus_rdt, dbus_rdt;
   reg         ibus_ack = 1'b0, dbus_ack = 1'b0;

   wire [8:0]  rf_waddr, rf_raddr;
   wire [1:0]  rf_wdata;
   wire        rf_wen, rf_ren;
   wire [1:0]  rf_rdata;

   serv_system dut
     (.clk (clk), .i_rst (rst),
      .o_ibus_adr (ibus_adr), .o_ibus_cyc (ibus_cyc), .i_ibus_rdt (ibus_rdt), .i_ibus_ack (ibus_ack),
      .o_dbus_adr (dbus_adr), .o_dbus_dat (dbus_dat), .o_dbus_sel (dbus_sel), .o_dbus_we (dbus_we),
      .o_dbus_cyc (dbus_cyc), .i_dbus_rdt (dbus_rdt), .i_dbus_ack (dbus_ack),
      .o_rf_waddr (rf_waddr), .o_rf_wdata (rf_wdata), .o_rf_wen (rf_wen),
      .o_rf_raddr (rf_raddr), .o_rf_ren (rf_ren), .i_rf_rdata (rf_rdata));

   // memória de programa e dados: 256 palavras de 32 bits
   reg [31:0] mem [0:255];
   integer i;
   initial begin
      for (i = 0; i < 256; i = i + 1) mem[i] = 32'h0000_0013;   // nop
      mem[0] = 32'h0280_0093;                                   // addi x1, x0, 40
      mem[1] = 32'h0020_0113;                                   // addi x2, x0, 2
      mem[2] = 32'h0020_80B3;                                   // add  x1, x1, x2
      mem[3] = 32'h1010_2023;                                   // sw   x1, 256(x0)
      mem[4] = 32'h0000_006F;                                   // jal  x0, 0
      mem[64] = 32'h0000_0000;                                  // 0x100
   end

   always @(posedge clk) begin
      ibus_ack <= #5 (ibus_cyc & !ibus_ack);
      ibus_rdt <= #5 mem[ibus_adr[9:2]];
      dbus_ack <= #5 (dbus_cyc & !dbus_ack);
      dbus_rdt <= #5 mem[dbus_adr[9:2]];
      if (dbus_cyc & !dbus_ack & dbus_we) begin
         if (dbus_sel[0]) mem[dbus_adr[9:2]][7:0]   <= #5 dbus_dat[7:0];
         if (dbus_sel[1]) mem[dbus_adr[9:2]][15:8]  <= #5 dbus_dat[15:8];
         if (dbus_sel[2]) mem[dbus_adr[9:2]][23:16] <= #5 dbus_dat[23:16];
         if (dbus_sel[3]) mem[dbus_adr[9:2]][31:24] <= #5 dbus_dat[31:24];
      end
   end

   // SRAM do banco de registradores (como serv_rf_ram.v): leitura síncrona,
   // e x0 sempre lido como zero
   reg [1:0] rf [0:511];
   reg [1:0] rf_q;
   reg       rf_zero;
   initial for (i = 0; i < 512; i = i + 1) rf[i] = 2'b00;
   always @(posedge clk) begin
      if (rf_wen) rf[rf_waddr] <= #5 rf_wdata;
      rf_q    <= #5 rf[rf_raddr];
      rf_zero <= #5 (rf_raddr[8:4] == 5'd0);
   end
   assign rf_rdata = rf_q & ~{2{rf_zero}};

   integer cyc = 0;
   initial begin
      repeat (5) @(posedge clk);
      @(negedge clk);
      rst <= 1'b0;
      while (!(dbus_cyc & dbus_we & dbus_ack) && cyc < 1000) begin
         @(posedge clk);
         cyc = cyc + 1;
      end
      @(posedge clk);
      if (mem[64] !== 32'd42) begin
         $display("FALHOU: mem[0x100] = %0d (esperado 42) após %0d ciclos", mem[64], cyc);
         $finish(1);
      end
      $display("OK: serv_system: 40 + 2 = %0d em %0d ciclos de clock", mem[64], cyc);
      $finish(0);
   end
endmodule
