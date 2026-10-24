// tb_serv_clk_mem_board.sv : Testbench da Placa de Clock e Memórias do SERV
`timescale 1ns/1ps

module tb_serv_clk_mem_board;

   reg raw_clk = 1'b0;
   reg rst_btn = 1'b0;
   reg step_btn = 1'b0;
   reg auto_mode = 1'b1;

   always #25 raw_clk = ~raw_clk; // 20 MHz base clock -> gera 10 MHz o_clk

   wire o_clk;
   wire o_rst;

   // Barramentos
   reg  [31:0] ibus_adr = 32'd0;
   reg         ibus_cyc = 1'b0;
   wire [31:0] ibus_rdt;
   wire        ibus_ack;

   reg  [31:0] dbus_adr = 32'd0;
   reg  [31:0] dbus_dat = 32'd0;
   reg  [3:0]  dbus_sel = 4'b1111;
   reg         dbus_we  = 1'b0;
   reg         dbus_cyc = 1'b0;
   wire [31:0] dbus_rdt;
   wire        dbus_ack;

   reg  [8:0]  rf_waddr = 9'd0;
   reg  [1:0]  rf_wdata = 2'd0;
   reg         rf_wen   = 1'b0;
   reg  [8:0]  rf_raddr = 9'd0;
   reg         rf_ren   = 1'b0;
   wire [1:0]  rf_rdata;

   wire [7:0]  debug_leds;
   wire        bus_busy;

   serv_clk_mem_board u_board (
      .i_raw_clk     (raw_clk),
      .i_rst_btn     (rst_btn),
      .i_step_btn    (step_btn),
      .i_auto_mode   (auto_mode),

      .o_clk         (o_clk),
      .o_rst         (o_rst),

      .i_ibus_adr    (ibus_adr),
      .i_ibus_cyc    (ibus_cyc),
      .o_ibus_rdt    (ibus_rdt),
      .o_ibus_ack    (ibus_ack),

      .i_dbus_adr    (dbus_adr),
      .i_dbus_dat    (dbus_dat),
      .i_dbus_sel    (dbus_sel),
      .i_dbus_we     (dbus_we),
      .i_dbus_cyc    (dbus_cyc),
      .o_dbus_rdt    (dbus_rdt),
      .o_dbus_ack    (dbus_ack),

      .i_rf_waddr    (rf_waddr),
      .i_rf_wdata    (rf_wdata),
      .i_rf_wen      (rf_wen),
      .i_rf_raddr    (rf_raddr),
      .i_rf_ren      (rf_ren),
      .o_rf_rdata    (rf_rdata),

      .o_debug_leds  (debug_leds),
      .o_bus_busy    (bus_busy)
   );

   initial begin
      // Pulso inicial de reset
      rst_btn = 1'b1;
      #200;
      rst_btn = 1'b0;
      #200;

      // 1. Testa Leitura na ROM (0x00: addi x1, x0, 40 -> 0x02800093)
      @(posedge o_clk);
      ibus_adr <= 32'h0000_0000;
      ibus_cyc <= 1'b1;
      @(posedge o_clk);
      while (!ibus_ack) @(posedge o_clk);
      if (ibus_rdt !== 32'h0280_0093) begin
         $display("ERRO ROM 0x00: esperado 0x02800093, obtido %h", ibus_rdt);
         $finish(1);
      end
      $display("OK: ROM 0x00 leu instrucao addi: %h (ACK=%b)", ibus_rdt, ibus_ack);
      ibus_cyc <= 1'b0;

      // 2. Testa Escrita na RAM (0x100 = 32'hDEADBEEF)
      @(posedge o_clk);
      dbus_adr <= 32'h0000_0100;
      dbus_dat <= 32'hDEAD_BEEF;
      dbus_sel <= 4'b1111;
      dbus_we  <= 1'b1;
      dbus_cyc <= 1'b1;
      @(posedge o_clk);
      while (!dbus_ack) @(posedge o_clk);
      $display("OK: RAM gravada em 0x100 com dado 0xDEADBEEF (ACK=%b)", dbus_ack);
      dbus_we  <= 1'b0;
      dbus_cyc <= 1'b0;

      // 3. Testa Leitura na RAM (0x100)
      @(posedge o_clk);
      dbus_adr <= 32'h0000_0100;
      dbus_we  <= 1'b0;
      dbus_cyc <= 1'b1;
      @(posedge o_clk);
      while (!dbus_ack) @(posedge o_clk);
      if (dbus_rdt !== 32'hDEAD_BEEF) begin
         $display("ERRO RAM 0x100: esperado 0xDEADBEEF, obtido %h", dbus_rdt);
         $finish(1);
      end
      $display("OK: RAM lida em 0x100: %h", dbus_rdt);
      dbus_cyc <= 1'b0;

      // 4. Testa Escrita no Periférico MMIO LEDs (0x200 = 8'h2A = 42 decimal)
      @(posedge o_clk);
      dbus_adr <= 32'h0000_0200;
      dbus_dat <= 32'h0000_002A;
      dbus_sel <= 4'b0001;
      dbus_we  <= 1'b1;
      dbus_cyc <= 1'b1;
      @(posedge o_clk);
      while (!dbus_ack) @(posedge o_clk);
      @(posedge o_clk);
      if (debug_leds !== 8'h2A) begin
         $display("ERRO MMIO LEDs: esperado 0x2A, obtido %h", debug_leds);
         $finish(1);
      end
      $display("OK: MMIO LEDs acionados com 0x2A (42): %b", debug_leds);
      dbus_we  <= 1'b0;
      dbus_cyc <= 1'b0;

      // 5. Testa SRAM do Banco de Registradores (RF: grava 2'b11 no endereço 9'd32)
      @(posedge o_clk);
      rf_waddr <= 9'd32;
      rf_wdata <= 2'b11;
      rf_wen   <= 1'b1;
      @(posedge o_clk);
      rf_wen   <= 1'b0;
      rf_raddr <= 9'd32;
      rf_ren   <= 1'b1;
      @(posedge o_clk);
      #5; // Aguarda propagação da leitura síncrona
      if (rf_rdata !== 2'b11) begin
         $display("ERRO SRAM RF: esperado 2'b11, obtido %b", rf_rdata);
         $finish(1);
      end
      $display("OK: SRAM RF leu valor 2'b11 no endereco 32: %b", rf_rdata);
      rf_ren   <= 1'b0;

      // 6. Testa hardwire de x0 = 0
      @(posedge o_clk);
      rf_raddr <= 9'd5; // registrador x0 (bits 8:4 == 0)
      rf_ren   <= 1'b1;
      @(posedge o_clk);
      #5;
      if (rf_rdata !== 2'b00) begin
         $display("ERRO SRAM RF x0: esperado 2'b00, obtido %b", rf_rdata);
         $finish(1);
      end
      $display("OK: SRAM RF registrador x0 hardwired para 0: %b", rf_rdata);

      $display("==========================================================");
      $display("[✓] Todos os testes da Placa de Clock e Memoria PASSARAM!");
      $display("==========================================================");
      $finish(0);
   end

endmodule
