// tb_serv_rf_if.sv : Testbench unitario e vetores de teste para serv_rf_if (Multiplexador RF em RTL)
`timescale 1ns/1ps

module tb_serv_rf_if;
   logic       clk = 1'b0;
   always #50 clk = ~clk;

   logic       i_cnt_en = 1'b1;
   logic [4:0] o_wreg0;
   logic [4:0] o_wreg1;
   logic       o_wen0;
   logic       o_wen1;
   logic       o_wdata0;
   logic       o_wdata1;
   logic [4:0] o_rreg0;
   logic [4:0] o_rreg1;
   logic       i_rdata0 = 1'b0;
   logic       i_rdata1 = 1'b0;
   logic       i_rd_wen = 1'b1;
   logic [4:0] i_rd_waddr = 5'd0;
   logic       i_ctrl_rd = 1'b0;
   logic       i_alu_rd = 1'b0;
   logic       i_rd_alu_en = 1'b0;
   logic       i_mem_rd = 1'b0;
   logic       i_rd_mem_en = 1'b0;
   logic [4:0] i_rs1_raddr = 5'd0;
   logic       o_rs1;
   logic [4:0] i_rs2_raddr = 5'd0;
   logic       o_rs2;

   serv_rf_if dut (
      .i_cnt_en    (i_cnt_en),
      .o_wreg0     (o_wreg0),
      .o_wreg1     (o_wreg1),
      .o_wen0      (o_wen0),
      .o_wen1      (o_wen1),
      .o_wdata0    (o_wdata0),
      .o_wdata1    (o_wdata1),
      .o_rreg0     (o_rreg0),
      .o_rreg1     (o_rreg1),
      .i_rdata0    (i_rdata0),
      .i_rdata1    (i_rdata1),
      .i_rd_wen    (i_rd_wen),
      .i_rd_waddr  (i_rd_waddr),
      .i_ctrl_rd   (i_ctrl_rd),
      .i_alu_rd    (i_alu_rd),
      .i_rd_alu_en (i_rd_alu_en),
      .i_mem_rd    (i_mem_rd),
      .i_rd_mem_en (i_rd_mem_en),
      .i_rs1_raddr (i_rs1_raddr),
      .o_rs1       (o_rs1),
      .i_rs2_raddr (i_rs2_raddr),
      .o_rs2       (o_rs2)
   );

   integer errors = 0;
   integer tests_run = 0;

   initial begin
      $display("\n========================================================");
      $display(" INICIANDO TESTES UNITARIOS: serv_rf_if (Interface RF em RTL)");
      $display("========================================================");

      #10;

      // 1. Bloqueio de escrita em x0 (hardwired zero)
      tests_run++;
      i_rd_wen   = 1'b1;
      i_rd_waddr = 5'd0; // x0
      i_cnt_en   = 1'b1;
      #1;
      if (o_wen0 !== 1'b0) begin
         $display(" [FAIL] x0: o_wen0 deveria ser 0 (escrita em x0 deve ser bloqueada)");
         errors++;
      end else begin
         $display(" [PASS] Bloqueio em x0 ativo: o_wen0 = 0");
      end

      // 2. Habilitação de escrita para x1..x31
      tests_run++;
      i_rd_waddr = 5'd1;
      #1;
      if (o_wen0 !== 1'b1 || o_wreg0 !== 5'd1) begin
         $display(" [FAIL] x1: o_wen0=%b (exp 1) o_wreg0=%0d (exp 1)", o_wen0, o_wreg0);
         errors++;
      end else begin
         $display(" [PASS] Escrita em x1 habilitada: wen0=1, wreg0=1");
      end

      // 3. Mux de fontes de escrita: ALU
      tests_run++;
      i_alu_rd    = 1'b1;
      i_rd_alu_en = 1'b1;
      i_mem_rd    = 1'b0;
      i_rd_mem_en = 1'b0;
      i_ctrl_rd   = 1'b0;
      #1;
      if (o_wdata0 !== 1'b1) begin
         $display(" [FAIL] Mux ALU falhou!");
         errors++;
      end else begin
         $display(" [PASS] Fonte ALU selecionada para escrita em RD");
      end

      // 4. Mux de fontes de escrita: Memória
      tests_run++;
      i_alu_rd    = 1'b0;
      i_rd_alu_en = 1'b0;
      i_mem_rd    = 1'b1;
      i_rd_mem_en = 1'b1;
      #1;
      if (o_wdata0 !== 1'b1) begin
         $display(" [FAIL] Mux Memória falhou!");
         errors++;
      end else begin
         $display(" [PASS] Fonte Memoria selecionada para escrita em RD");
      end

      // 5. Encaminhamento de leitura de RS1 e RS2
      tests_run++;
      i_rdata0 = 1'b1;
      i_rdata1 = 1'b0;
      i_rs1_raddr = 5'd10;
      i_rs2_raddr = 5'd11;
      #1;
      if (o_rs1 !== 1'b1 || o_rs2 !== 1'b0 || o_rreg0 !== 5'd10 || o_rreg1 !== 5'd11) begin
         $display(" [FAIL] Leitura RS1/RS2 falhou!");
         errors++;
      end else begin
         $display(" [PASS] Leitura RS1 (x10) e RS2 (x11) encaminhada com precisao");
      end

      $display("========================================================");
      if (errors == 0) begin
         $display(" [SUCESSO] Todos os %0d testes de serv_rf_if passaram!", tests_run);
         $display("========================================================\n");
         $finish(0);
      end else begin
         $display(" [FALHA] %0d de %0d testes falharam em serv_rf_if!", errors, tests_run);
         $display("========================================================\n");
         $finish(1);
      end
   end
endmodule
