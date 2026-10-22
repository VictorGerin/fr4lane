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

   serv_pkg::sys_req_t sys_req;
   serv_pkg::sys_rsp_t sys_rsp;

   // Registradores MMIO para comunicacao C <-> Testbench
   reg [31:0]  test_result = 32'd0;
   reg         test_finish = 1'b0;

   serv_system #(
      .PC_WIDTH (PC_WIDTH),
      .WITH_E   (WITH_E)
   ) dut (
      .clk   (clk),
      .i_rst (rst),
      .o_sys (sys_req),
      .i_sys (sys_rsp)
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

   // SRAM do banco de registradores (256x2 para RV32E, 512x2 para RV32I)
   reg [1:0] rf [0:RF_DEPTH-1];
   initial for (i = 0; i < RF_DEPTH; i = i + 1) rf[i] = 2'b00;

   // Logica de leitura e escrita do Wishbone e SRAM
   initial begin
      sys_rsp = '0;
   end

   always @(posedge clk) begin
      sys_rsp.ibus.ack <= #5 (sys_req.ibus.cyc & !sys_rsp.ibus.ack);
      sys_rsp.ibus.rdt <= #5 mem[sys_req.ibus.adr[12:2]];

      sys_rsp.dbus.ack <= #5 (sys_req.dbus.cyc & !sys_rsp.dbus.ack);
      
      // Leitura de dados
      if (sys_req.dbus.adr == 32'h0000_2000)
         sys_rsp.dbus.rdt <= #5 test_result;
      else if (sys_req.dbus.adr == 32'h0000_2004)
         sys_rsp.dbus.rdt <= #5 {31'b0, test_finish};
      else
         sys_rsp.dbus.rdt <= #5 mem[sys_req.dbus.adr[12:2]];

      // Escrita de dados
      if (sys_req.dbus.cyc & !sys_rsp.dbus.ack & sys_req.dbus.we) begin
         if (sys_req.dbus.adr == 32'h0000_2000) begin
            test_result <= sys_req.dbus.dat;
         end else if (sys_req.dbus.adr == 32'h0000_2004) begin
            test_finish <= sys_req.dbus.dat[0];
         end else if (sys_req.dbus.adr < 32'h0000_2000) begin
            if (sys_req.dbus.sel[0]) mem[sys_req.dbus.adr[12:2]][7:0]   <= #5 sys_req.dbus.dat[7:0];
            if (sys_req.dbus.sel[1]) mem[sys_req.dbus.adr[12:2]][15:8]  <= #5 sys_req.dbus.dat[15:8];
            if (sys_req.dbus.sel[2]) mem[sys_req.dbus.adr[12:2]][23:16] <= #5 sys_req.dbus.dat[23:16];
            if (sys_req.dbus.sel[3]) mem[sys_req.dbus.adr[12:2]][31:24] <= #5 sys_req.dbus.dat[31:24];
         end
      end

      // SRAM RF
      if (sys_req.rf.wen) rf[sys_req.rf.waddr[AW_RF-1:0]] <= #5 sys_req.rf.wdata;
      sys_rsp.rf.rdata <= #5 rf[sys_req.rf.raddr[AW_RF-1:0]] & ~{2{(sys_req.rf.raddr[AW_RF-1:4] == 4'd0)}};
   end

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
