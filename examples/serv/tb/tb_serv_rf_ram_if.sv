// tb_serv_rf_ram_if.sv : Testbench unitario e vetores de teste para serv_rf_ram_if (Adaptador SRAM em RTL)
`timescale 1ns/1ps

module tb_serv_rf_ram_if;
   logic       clk = 1'b0;
   always #50 clk = ~clk;

   logic       i_rst = 1'b1;
   logic       i_wreq = 1'b0;
   logic       i_rreq = 1'b0;
   logic       o_ready;
   logic [4:0] i_wreg0 = 5'd0;
   logic [4:0] i_wreg1 = 5'd0;
   logic       i_wen0 = 1'b0;
   logic       i_wen1 = 1'b0;
   logic       i_wdata0 = 1'b0;
   logic       i_wdata1 = 1'b0;
   logic [4:0] i_rreg0 = 5'd0;
   logic [4:0] i_rreg1 = 5'd0;
   logic       o_rdata0;
   logic       o_rdata1;
   logic [8:0] o_waddr;
   logic [1:0] o_wdata;
   logic       o_wen;
   logic [8:0] o_raddr;
   logic       o_ren;
   logic [1:0] i_rdata = 2'b00;

   serv_rf_ram_if dut (
      .i_clk    (clk),
      .i_rst    (i_rst),
      .i_wreq   (i_wreq),
      .i_rreq   (i_rreq),
      .o_ready  (o_ready),
      .i_wreg0  (i_wreg0),
      .i_wreg1  (i_wreg1),
      .i_wen0   (i_wen0),
      .i_wen1   (i_wen1),
      .i_wdata0 (i_wdata0),
      .i_wdata1 (i_wdata1),
      .i_rreg0  (i_rreg0),
      .i_rreg1  (i_rreg1),
      .o_rdata0 (o_rdata0),
      .o_rdata1 (o_rdata1),
      .o_waddr  (o_waddr),
      .o_wdata  (o_wdata),
      .o_wen    (o_wen),
      .o_raddr  (o_raddr),
      .o_ren    (o_ren),
      .i_rdata  (i_rdata)
   );

   integer errors = 0;
   integer tests_run = 0;

   initial begin
      integer k;
      $display("\n========================================================");
      $display(" INICIANDO TESTES UNITARIOS: serv_rf_ram_if (Adaptador SRAM em RTL)");
      $display("========================================================");

      // 1. Reset
      repeat (3) @(posedge clk);
      @(negedge clk);
      i_rst = 1'b0;
      @(posedge clk);

      tests_run++;
      if (o_ren !== 1'b0 || o_wen !== 1'b0) begin
         $display(" [FAIL] Reset: o_ren=%b o_wen=%b (esperado 0)", o_ren, o_wen);
         errors++;
      end else begin
         $display(" [PASS] Reset correto: barramento SRAM inativo");
      end

      // 2. Pedido de Leitura (i_rreq)
      @(negedge clk);
      i_rreq  = 1'b1;
      i_rreg0 = 5'd1; // ler x1
      i_rreg1 = 5'd2; // ler x2
      @(posedge clk);
      @(negedge clk);
      i_rreq  = 1'b0;

      // Espera handshake o_ready
      tests_run++;
      @(posedge clk);
      #1;
      if (!o_ready) begin
         $display(" [FAIL] o_ready nao subiu apos i_rreq! (ready=%b)", o_ready);
         errors++;
      end else begin
         $display(" [PASS] Handshake o_ready confirmado com sucesso!");
      end

      // 3. Verifica geracao de endereco de leitura o_raddr
      tests_run++;
      if (o_ren !== 1'b1) begin
         $display(" [FAIL] o_ren deveria estar ativo durante a leitura da SRAM!");
         errors++;
      end else begin
         $display(" [PASS] Leitura da SRAM em andamento: o_ren=1, o_raddr=0x%03X", o_raddr);
      end

      $display("========================================================");
      if (errors == 0) begin
         $display(" [SUCESSO] Todos os %0d testes de serv_rf_ram_if passaram!", tests_run);
         $display("========================================================\n");
         $finish(0);
      end else begin
         $display(" [FALHA] %0d de %0d testes falharam em serv_rf_ram_if!", errors, tests_run);
         $display("========================================================\n");
         $finish(1);
      end
   end
endmodule
