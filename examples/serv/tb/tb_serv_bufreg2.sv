// tb_serv_bufreg2.sv : Testbench unitario e vetores de teste para serv_bufreg2 (Segundo Buffer em RTL)
`timescale 1ns/1ps

module tb_serv_bufreg2;
   logic        clk = 1'b0;
   always #50 clk = ~clk;

   logic        i_en = 1'b0;
   logic        i_init = 1'b0;
   logic        i_cnt7 = 1'b0;
   logic        i_cnt_done = 1'b0;
   logic        i_sh_right = 1'b0;
   logic [1:0]  i_lsb = 2'b00;
   logic [1:0]  i_bytecnt = 2'b00;
   logic        o_sh_done;
   logic        i_op_b_sel = 1'b1;
   logic        i_shift_op = 1'b0;
   logic        i_rs2 = 1'b0;
   logic        i_imm = 1'b0;
   logic        o_op_b;
   logic        o_q;
   logic [31:0] o_dat;
   logic        i_load = 1'b0;
   logic [31:0] i_dat = 32'd0;

   serv_bufreg2 dut (
      .i_clk       (clk),
      .i_en        (i_en),
      .i_init      (i_init),
      .i_cnt7      (i_cnt7),
      .i_cnt_done  (i_cnt_done),
      .i_sh_right  (i_sh_right),
      .i_lsb       (i_lsb),
      .i_bytecnt   (i_bytecnt),
      .o_sh_done   (o_sh_done),
      .i_op_b_sel  (i_op_b_sel),
      .i_shift_op  (i_shift_op),
      .i_rs2       (i_rs2),
      .i_imm       (i_imm),
      .o_op_b      (o_op_b),
      .o_q         (o_q),
      .o_dat       (o_dat),
      .i_load      (i_load),
      .i_dat       (i_dat)
   );

   integer errors = 0;
   integer tests_run = 0;

   initial begin
      integer k;
      $display("\n========================================================");
      $display(" INICIANDO TESTES UNITARIOS: serv_bufreg2 (Buffer 2 em RTL)");
      $display("========================================================");

      repeat (2) @(posedge clk);

      // 1. Carga paralela de dados da memoria (LOAD de 32 bits)
      tests_run++;
      @(negedge clk);
      i_load = 1'b1;
      i_dat  = 32'hDEADBEEF;
      @(posedge clk);
      @(negedge clk);
      i_load = 1'b0;
      #1;

      if (o_dat !== 32'hDEADBEEF) begin
         $display(" [FAIL] Carga paralela: o_dat = 0x%08X (esperado 0xDEADBEEF)", o_dat);
         errors++;
      end else begin
         $display(" [PASS] Carga paralela de 32 bits com sucesso: o_dat = 0x%08X", o_dat);
      end

      // 2. Selecao de operando B (Mux RS2 vs IMM)
      tests_run++;
      i_rs2 = 1'b1;
      i_imm = 1'b0;
      i_op_b_sel = 1'b1;
      #1;
      if (o_op_b !== 1'b1) begin
         $display(" [FAIL] Mux op_b sel RS2 falhou!");
         errors++;
      end else begin
         $display(" [PASS] Mux op_b seleciona RS2 corretamente");
      end

      tests_run++;
      i_op_b_sel = 1'b0;
      #1;
      if (o_op_b !== 1'b0) begin
         $display(" [FAIL] Mux op_b sel IMM falhou!");
         errors++;
      end else begin
         $display(" [PASS] Mux op_b seleciona IMM corretamente");
      end

      $display("========================================================");
      if (errors == 0) begin
         $display(" [SUCESSO] Todos os %0d testes de serv_bufreg2 passaram!", tests_run);
         $display("========================================================\n");
         $finish(0);
      end else begin
         $display(" [FALHA] %0d de %0d testes falharam em serv_bufreg2!", errors, tests_run);
         $display("========================================================\n");
         $finish(1);
      end
   end
endmodule
