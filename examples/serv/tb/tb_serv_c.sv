// tb_serv_c.sv : Testbench do SERV para execucao de programas compilados em C
//
// Modela memoria de programa/dados (8 KB) com barramento Wishbone e mapeamento MMIO:
//   - 0x0000_0000 a 0x0000_1FFF : RAM (8 KB)
//   - 0x0000_2000               : TEST_RESULT (retorno de main / valor do teste)
//   - 0x0000_2004               : TEST_FINISH (escrita de 1 sinaliza conclusao)
//
`timescale 1ns/1ps
module tb_serv_c #(
   parameter int PC_WIDTH = 32
);
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

   // Registradores MMIO para comunicacao C <-> Testbench
   reg [31:0]  test_result = 32'd0;
   reg         test_finish = 1'b0;

   serv_system #(
      .PC_WIDTH (PC_WIDTH)
   ) dut
     (.clk        (clk),
      .i_rst      (rst),
      .o_ibus_adr (ibus_adr),
      .o_ibus_cyc (ibus_cyc),
      .i_ibus_rdt (ibus_rdt),
      .i_ibus_ack (ibus_ack),
      .o_dbus_adr (dbus_adr),
      .o_dbus_dat (dbus_dat),
      .o_dbus_sel (dbus_sel),
      .o_dbus_we  (dbus_we),
      .o_dbus_cyc (dbus_cyc),
      .i_dbus_rdt (dbus_rdt),
      .i_dbus_ack (dbus_ack),
      .o_rf_waddr (rf_waddr),
      .o_rf_wdata (rf_wdata),
      .o_rf_wen   (rf_wen),
      .o_rf_raddr (rf_raddr),
      .o_rf_ren   (rf_ren),
      .i_rf_rdata (rf_rdata));

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
   always @(posedge clk) begin
      ibus_ack <= #5 (ibus_cyc & !ibus_ack);
      ibus_rdt <= #5 mem[ibus_adr[12:2]];

      dbus_ack <= #5 (dbus_cyc & !dbus_ack);
      
      // Leitura de dados
      if (dbus_adr == 32'h0000_2000)
         dbus_rdt <= #5 test_result;
      else if (dbus_adr == 32'h0000_2004)
         dbus_rdt <= #5 {31'b0, test_finish};
      else
         dbus_rdt <= #5 mem[dbus_adr[12:2]];

      // Escrita de dados
      if (dbus_cyc & !dbus_ack & dbus_we) begin
         if (dbus_adr == 32'h0000_2000) begin
            test_result <= dbus_dat;
         end else if (dbus_adr == 32'h0000_2004) begin
            test_finish <= dbus_dat[0];
         end else if (dbus_adr < 32'h0000_2000) begin
            if (dbus_sel[0]) mem[dbus_adr[12:2]][7:0]   <= #5 dbus_dat[7:0];
            if (dbus_sel[1]) mem[dbus_adr[12:2]][15:8]  <= #5 dbus_dat[15:8];
            if (dbus_sel[2]) mem[dbus_adr[12:2]][23:16] <= #5 dbus_dat[23:16];
            if (dbus_sel[3]) mem[dbus_adr[12:2]][31:24] <= #5 dbus_dat[31:24];
         end
      end
   end

   // SRAM do banco de registradores (512 x 2 bits, x0 sempre le zero)
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
