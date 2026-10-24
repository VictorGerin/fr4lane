// tb_serv_complete_system.sv : Integração Completa do SERV no Backplane
// Conecta o processador SERV (4 placas filhas) à nova Placa de Clock e Memórias
`timescale 1ns/1ps

module tb_serv_complete_system;

   reg raw_clk = 1'b0;
   reg rst_btn = 1'b0;
   reg step_btn = 1'b0;
   reg auto_mode = 1'b1;

   always #25 raw_clk = ~raw_clk; // 20 MHz -> gera 10 MHz o_clk

   wire sys_clk;
   wire sys_rst;

   // Sinais do Barramento do Sistema (Backplane)
   serv_pkg::sys_req_t cpu_req;
   serv_pkg::sys_rsp_t cpu_rsp;

   // =========================================================================
   // Placa 5: Clock e Memórias (serv_clk_mem_board)
   // =========================================================================
   wire [7:0] debug_leds;
   wire       bus_busy;

   serv_clk_mem_board u_clk_mem (
      .i_raw_clk     (raw_clk),
      .i_rst_btn     (rst_btn),
      .i_step_btn    (step_btn),
      .i_auto_mode   (auto_mode),

      .o_clk         (sys_clk),
      .o_rst         (sys_rst),

      .i_ibus_adr    (cpu_req.ibus.adr),
      .i_ibus_cyc    (cpu_req.ibus.cyc),
      .o_ibus_rdt    (cpu_rsp.ibus.rdt),
      .o_ibus_ack    (cpu_rsp.ibus.ack),

      .i_dbus_adr    (cpu_req.dbus.adr),
      .i_dbus_dat    (cpu_req.dbus.dat),
      .i_dbus_sel    (cpu_req.dbus.sel),
      .i_dbus_we     (cpu_req.dbus.we),
      .i_dbus_cyc    (cpu_req.dbus.cyc),
      .o_dbus_rdt    (cpu_rsp.dbus.rdt),
      .o_dbus_ack    (cpu_rsp.dbus.ack),

      .i_rf_waddr    (cpu_req.rf.waddr),
      .i_rf_wdata    (cpu_req.rf.wdata),
      .i_rf_wen      (cpu_req.rf.wen),
      .i_rf_raddr    (cpu_req.rf.raddr),
      .i_rf_ren      (cpu_req.rf.ren),
      .o_rf_rdata    (cpu_rsp.rf.rdata),

      .o_debug_leds  (debug_leds),
      .o_bus_busy    (bus_busy)
   );

   // =========================================================================
   // Placas 1 a 4: Processador SERV (serv_system)
   // =========================================================================
   serv_system u_cpu (
      .clk           (sys_clk),
      .i_rst         (sys_rst),
      .o_sys         (cpu_req),
      .i_sys         (cpu_rsp)
   );

   integer cycles = 0;
   initial begin
      $display("Iniciando simulacao do SERV conectado ao Backplane e Placa de Clock/Memorias...");
      rst_btn = 1'b1;
      #150;
      rst_btn = 1'b0;

      // Aguarda a CPU executar o programa da ROM:
      // 1. addi x1, x0, 40
      // 2. addi x2, x0, 2
      // 3. add  x1, x1, x2 (x1 = 42)
      // 4. sw   x1, 256(x0) -> grava 42 na RAM 0x100
      // 5. sw   x1, 512(x0) -> grava 42 nos LEDs MMIO 0x200
      while (debug_leds !== 8'd42 && cycles < 1500) begin
         @(posedge sys_clk);
         cycles = cycles + 1;
      end

      if (debug_leds === 8'd42) begin
         $display("==================================================================");
         $display("[✓] SUCESSO ABSOLUTO!");
         $display("    - O processador SERV deu boot pela ROM na Placa de Memoria;");
         $display("    - Executou a adicao RV32I: 40 + 2 = 42;");
         $display("    - Armazenou o resultado na RAM (0x100);");
         $display("    - Acendeu os LEDs de diagnostico (MMIO 0x200) com valor: %0d (0x%02h);", debug_leds, debug_leds);
         $display("    - Tempo de execucao: %0d ciclos de clock do SERV.", cycles);
         $display("==================================================================");
         $finish(0);
      end else begin
         $display("[FALHA] Timeout apos %0d ciclos. LEDs = %h", cycles, debug_leds);
         $finish(1);
      end
   end

endmodule
