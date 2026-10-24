// tb_serv_clk_mem_ctrl.sv : Testbench do Controlador Discreto RTL de Clock e Memória
`timescale 1ns/1ps

module tb_serv_clk_mem_ctrl;

   reg raw_clk = 1'b0;
   reg rst_btn = 1'b0;
   reg step_btn = 1'b0;
   reg auto_mode = 1'b1;

   always #25 raw_clk = ~raw_clk;

   wire o_clk;
   wire o_rst;

   reg  [31:0] ibus_adr = 32'd0;
   reg         ibus_cyc = 1'b0;
   wire        ibus_ack;

   reg  [31:0] dbus_adr = 32'd0;
   reg  [7:0]  dbus_dat = 8'd0;
   reg         dbus_we  = 1'b0;
   reg         dbus_cyc = 1'b0;
   wire        dbus_ack;

   wire        rom_cs;
   wire        ram_cs;
   wire        mmio_cs;
   wire [7:0]  debug_leds;
   wire        bus_busy;

   serv_clk_mem_ctrl dut (
      .i_raw_clk     (raw_clk),
      .i_rst_btn     (rst_btn),
      .i_step_btn    (step_btn),
      .i_auto_mode   (auto_mode),

      .o_clk         (o_clk),
      .o_rst         (o_rst),

      .i_ibus_adr    (ibus_adr),
      .i_ibus_cyc    (ibus_cyc),
      .o_ibus_ack    (ibus_ack),

      .i_dbus_adr    (dbus_adr),
      .i_dbus_dat    (dbus_dat),
      .i_dbus_we     (dbus_we),
      .i_dbus_cyc    (dbus_cyc),
      .o_dbus_ack    (dbus_ack),

      .o_rom_cs      (rom_cs),
      .o_ram_cs      (ram_cs),
      .o_mmio_cs     (mmio_cs),
      .o_debug_leds  (debug_leds),
      .o_bus_busy    (bus_busy)
   );

   initial begin
      rst_btn = 1'b1;
      #150;
      rst_btn = 1'b0;
      #200;

      // 1. Testa seleção e ACK da ROM em 0x00
      @(posedge o_clk);
      ibus_adr <= 32'h0000_0000;
      ibus_cyc <= 1'b1;
      @(posedge o_clk);
      while (!ibus_ack) @(posedge o_clk);
      if (!rom_cs) begin
         $display("FALHOU: rom_cs deveria estar ativo em 0x00");
         $finish(1);
      end
      $display("OK: ROM CS ativo em 0x00 com ACK");
      ibus_cyc <= 1'b0;

      // 2. Testa seleção e ACK da RAM em 0x100
      @(posedge o_clk);
      dbus_adr <= 32'h0000_0100;
      dbus_cyc <= 1'b1;
      @(posedge o_clk);
      while (!dbus_ack) @(posedge o_clk);
      if (!ram_cs) begin
         $display("FALHOU: ram_cs deveria estar ativo em 0x100");
         $finish(1);
      end
      $display("OK: RAM CS ativo em 0x100 com ACK");
      dbus_cyc <= 1'b0;

      // 3. Testa escrita no registrador MMIO LEDs em 0x200
      @(posedge o_clk);
      dbus_adr <= 32'h0000_0200;
      dbus_dat <= 8'h2A; // 42 decimal
      dbus_we  <= 1'b1;
      dbus_cyc <= 1'b1;
      @(posedge o_clk);
      while (!dbus_ack) @(posedge o_clk);
      @(posedge o_clk);
      if (debug_leds !== 8'h2A) begin
         $display("FALHOU: LEDs deveriam ser 0x2A, obtido %h", debug_leds);
         $finish(1);
      end
      $display("OK: MMIO LEDs acionados com 0x2A (42)");
      dbus_we  <= 1'b0;
      dbus_cyc <= 1'b0;

      $display("==================================================================");
      $display("[✓] Todos os testes do Controlador RTL de Clock e Memoria PASSARAM!");
      $display("==================================================================");
      $finish(0);
   end

endmodule
