// tb_serv_mem_if.sv : Testbench unitario e vetores de teste para serv_mem_if (Interface de Memoria em RTL)
`timescale 1ns/1ps

module tb_serv_mem_if;
   logic       clk = 1'b0;
   always #50 clk = ~clk;

   logic [1:0] i_bytecnt = 2'b00;
   logic [1:0] i_lsb = 2'b00;
   logic       o_misalign;
   logic       i_signed = 1'b0;
   logic       i_word = 1'b0;
   logic       i_half = 1'b0;
   logic       i_bufreg2_q = 1'b0;
   logic       o_rd;
   logic [3:0] o_wb_sel;

   serv_mem_if dut (
      .i_clk       (clk),
      .i_bytecnt   (i_bytecnt),
      .i_lsb       (i_lsb),
      .o_misalign  (o_misalign),
      .i_signed    (i_signed),
      .i_word      (i_word),
      .i_half      (i_half),
      .i_bufreg2_q (i_bufreg2_q),
      .o_rd        (o_rd),
      .o_wb_sel    (o_wb_sel)
   );

   integer errors = 0;
   integer tests_run = 0;

   task automatic check_sel(
      input       word,
      input       half,
      input [1:0] lsb,
      input [3:0] exp_sel,
      input string desc
   );
      tests_run++;
      i_word = word;
      i_half = half;
      i_lsb  = lsb;
      #1;
      if (o_wb_sel !== exp_sel) begin
         $display(" [FAIL] %s: sel=%b (esperado: %b)", desc, o_wb_sel, exp_sel);
         errors++;
      end else begin
         $display(" [PASS] %s: Wishbone sel = %b", desc, o_wb_sel);
      end
   endtask

   initial begin
      $display("\n========================================================");
      $display(" INICIANDO TESTES UNITARIOS: serv_mem_if (Memoria em RTL)");
      $display("========================================================");

      repeat (2) @(posedge clk);

      // 1. Acesso a Palavra (Word - 32 bits)
      check_sel(1'b1, 1'b0, 2'b00, 4'b1111, "Word (32-bit): sel 1111");

      // 2. Acesso a Byte em cada posicao (0, 1, 2, 3)
      check_sel(1'b0, 1'b0, 2'b00, 4'b0001, "Byte offset 0: sel 0001");
      check_sel(1'b0, 1'b0, 2'b01, 4'b0010, "Byte offset 1: sel 0010");
      check_sel(1'b0, 1'b0, 2'b10, 4'b0100, "Byte offset 2: sel 0100");
      check_sel(1'b0, 1'b0, 2'b11, 4'b1000, "Byte offset 3: sel 1000");

      // 3. Acesso a Meia-Palavra (Halfword - 16 bits)
      check_sel(1'b0, 1'b1, 2'b00, 4'b0011, "Halfword offset 0: sel 0011");
      check_sel(1'b0, 1'b1, 2'b10, 4'b1100, "Halfword offset 2: sel 1100");

      $display("========================================================");
      if (errors == 0) begin
         $display(" [SUCESSO] Todos os %0d testes de serv_mem_if passaram!", tests_run);
         $display("========================================================\n");
         $finish(0);
      end else begin
         $display(" [FALHA] %0d de %0d testes falharam em serv_mem_if!", errors, tests_run);
         $display("========================================================\n");
         $finish(1);
      end
   end
endmodule
