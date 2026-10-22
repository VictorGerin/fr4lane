// tb_serv_c.sv : Testbench do SERV para execucao de programas compilados em C
//
// Modela memoria de programa/dados (8 KB) com barramento Wishbone e mapeamento MMIO:
//   - 0x0000_0000 a 0x0000_1FFF : RAM (8 KB)
//   - 0x0000_2000               : TEST_RESULT (retorno de main / valor do teste)
//   - 0x0000_2004               : TEST_FINISH (escrita de 1 sinaliza conclusao)
//
`timescale 1ns/1ps
module tb_serv_c #(
   parameter int PC_WIDTH = 13,
   parameter bit WITH_E   = 1'b0
);
   localparam int WREG     = WITH_E ? 4 : 5;
   localparam int AW_RF    = WITH_E ? 8 : 9;
   localparam int RF_DEPTH = WITH_E ? 256 : 512;

   reg clk = 1'b0;
   reg rst = 1'b1;
   always #50 clk = ~clk;

   serv_pkg::ibus_req_t ibus_req;
   serv_pkg::ibus_rsp_t ibus_rsp;
   serv_pkg::dbus_req_t dbus_req;
   serv_pkg::dbus_rsp_t dbus_rsp;
   serv_pkg::rf_req_t   rf_req;
   serv_pkg::rf_rsp_t   rf_rsp;

   // Registradores MMIO para comunicacao C <-> Testbench
   reg [31:0]  test_result = 32'd0;
   reg         test_finish = 1'b0;

   serv_system #(
      .PC_WIDTH (PC_WIDTH),
      .WITH_E   (WITH_E)
   ) dut (
      .clk    (clk),
      .i_rst  (rst),
      .o_ibus (ibus_req),
      .i_ibus (ibus_rsp),
      .o_dbus (dbus_req),
      .i_dbus (dbus_rsp),
      .o_rf   (rf_req),
      .i_rf   (rf_rsp)
   );

   // Memoria de programa e dados: 2048 palavras de 32 bits = 8 KB
   reg [31:0] mem [0:2047];
   integer i;

   // Carregamento de firmware via parametro de execucao
   string hex_file = "test_simple.hex";
   integer expected_val = 0;
   bit has_expected = 1'b0;
   integer timeout = 500000;

   initial begin
      for (i = 0; i < 2048; i = i + 1) mem[i] = 32'h0000_0013; // nop

      if ($value$plusargs("firmware=%s", hex_file)) begin
         $display("[TB] Carregando firmware: %s", hex_file);
      end else begin
         $display("[TB] Usando firmware padrao: %s", hex_file);
      end
      $readmemh(hex_file, mem);

      if ($value$plusargs("expected=%d", expected_val)) begin
         has_expected = 1'b1;
         $display("[TB] Valor esperado: %0d", expected_val);
      end

      if ($value$plusargs("timeout=%d", timeout)) begin
         $display("[TB] Timeout configurado para %0d ciclos", timeout);
      end
   end

   // Logica de leitura e escrita do Wishbone
   initial begin
      ibus_rsp = '0;
      dbus_rsp = '0;
   end

   always @(posedge clk) begin
      ibus_rsp.ack <= #5 (ibus_req.cyc & !ibus_rsp.ack);
      ibus_rsp.rdt <= #5 mem[ibus_req.adr[12:2]];

      dbus_rsp.ack <= #5 (dbus_req.cyc & !dbus_rsp.ack);
      
      // Leitura de dados
      if (dbus_req.adr == 32'h0000_2000)
         dbus_rsp.rdt <= #5 test_result;
      else if (dbus_req.adr == 32'h0000_2004)
         dbus_rsp.rdt <= #5 {31'b0, test_finish};
      else
         dbus_rsp.rdt <= #5 mem[dbus_req.adr[12:2]];

      // Escrita de dados
      if (dbus_req.cyc & !dbus_rsp.ack & dbus_req.we) begin
         if (dbus_req.adr == 32'h0000_2000) begin
            test_result <= dbus_req.dat;
         end else if (dbus_req.adr == 32'h0000_2004) begin
            test_finish <= dbus_req.dat[0];
         end else if (dbus_req.adr < 32'h0000_2000) begin
            if (dbus_req.sel[0]) mem[dbus_req.adr[12:2]][7:0]   <= #5 dbus_req.dat[7:0];
            if (dbus_req.sel[1]) mem[dbus_req.adr[12:2]][15:8]  <= #5 dbus_req.dat[15:8];
            if (dbus_req.sel[2]) mem[dbus_req.adr[12:2]][23:16] <= #5 dbus_req.dat[23:16];
            if (dbus_req.sel[3]) mem[dbus_req.adr[12:2]][31:24] <= #5 dbus_req.dat[31:24];
         end
      end
   end

   // SRAM do banco de registradores (256x2 para RV32E, 512x2 para RV32I)
   reg [1:0] rf [0:RF_DEPTH-1];
   reg [1:0] rf_q;
   reg       rf_zero;
   initial for (i = 0; i < RF_DEPTH; i = i + 1) rf[i] = 2'b00;
   always @(posedge clk) begin
      if (rf_req.wen) rf[rf_req.waddr[AW_RF-1:0]] <= #5 rf_req.wdata;
      rf_q    <= #5 rf[rf_req.raddr[AW_RF-1:0]];
      rf_zero <= #5 (rf_req.raddr[AW_RF-1:4] == 4'd0);
   end
   assign rf_rsp.rdata = rf_q & ~{2{rf_zero}};

   // Controle do teste e validacao
   integer cyc = 0;
   initial begin
      repeat (5) @(posedge clk);
      @(negedge clk);
      rst <= 1'b0;

      while (!test_finish && cyc < timeout) begin
         @(posedge clk);
         cyc = cyc + 1;
      end

      if (!test_finish) begin
         $display("\n========================================================");
         $display(" [FAIL] TIMEOUT: Processador nao finalizou apos %0d ciclos", cyc);
         $display("========================================================\n");
         $finish(1);
      end

      @(posedge clk);
      $display("\n========================================================");
      $display(" [INFO] Teste finalizou em %0d ciclos de clock.", cyc);
      $display(" [INFO] Valor retornado por main() / TEST_RESULT: %0d (0x%08X)", test_result, test_result);

      if (has_expected) begin
         if (test_result === expected_val) begin
            $display(" [PASS] RESULTADO CONFERE com o esperado (%0d)!", expected_val);
            $display("========================================================\n");
            $finish(0);
         end else begin
            $display(" [FAIL] RESULTADO INCORRETO! Esperado: %0d, Obtido: %0d", expected_val, test_result);
            $display("========================================================\n");
            $finish(1);
         end
      end else begin
         $display(" [OK] Execucao completada com sucesso.");
         $display("========================================================\n");
         $finish(0);
      end
   end
endmodule
