// tb_serv_alu.sv : Testbench unitario e vetores de teste para serv_alu (RTL)
`timescale 1ns/1ps

module tb_serv_alu;
   logic       clk = 1'b0;
   always #50 clk = ~clk;

   logic       i_en = 1'b0;
   logic       i_cnt0 = 1'b0;
   logic       o_cmp;
   logic       i_sub = 1'b0;
   logic [1:0] i_bool_op = 2'b00;
   logic       i_cmp_eq = 1'b0;
   logic       i_cmp_sig = 1'b0;
   logic [2:0] i_rd_sel = 3'b000;
   logic       i_rs1 = 1'b0;
   logic       i_op_b = 1'b0;
   logic       i_buf = 1'b0;
   logic       o_rd;

   serv_alu dut (
      .clk       (clk),
      .i_en      (i_en),
      .i_cnt0    (i_cnt0),
      .o_cmp     (o_cmp),
      .i_sub     (i_sub),
      .i_bool_op (i_bool_op),
      .i_cmp_eq  (i_cmp_eq),
      .i_cmp_sig (i_cmp_sig),
      .i_rd_sel  (i_rd_sel),
      .i_rs1     (i_rs1),
      .i_op_b    (i_op_b),
      .i_buf     (i_buf),
      .o_rd      (o_rd)
   );

   integer errors = 0;
   integer tests_run = 0;

   // Tarefa para rodar uma operação de 32 bits bit-serial
   task automatic run_op32(
      input [31:0] a,
      input [31:0] b,
      input        sub,
      input [1:0]  bool_op,
      input [2:0]  rd_sel,
      input        cmp_eq,
      input        cmp_sig,
      input [31:0] exp_rd,
      input        exp_cmp,
      input string op_name
   );
      logic [31:0] got_rd;
      logic        last_cmp;
      integer bit_idx;

      tests_run++;
      got_rd = 32'd0;

      // Estado ocioso antes da operação
      @(negedge clk);
      i_en      = 1'b0;
      i_sub     = sub;
      i_bool_op = bool_op;
      i_rd_sel  = rd_sel;
      i_cmp_eq  = cmp_eq;
      i_cmp_sig = cmp_sig;
      i_buf     = 1'b0;
      @(posedge clk);

      // Inicia os 32 ciclos seriais
      for (bit_idx = 0; bit_idx < 32; bit_idx++) begin
         @(negedge clk);
         i_en   = 1'b1;
         i_cnt0 = (bit_idx == 0);
         i_rs1  = a[bit_idx];
         i_op_b = b[bit_idx];
         @(posedge clk);
         got_rd[bit_idx] = o_rd;
         last_cmp        = o_cmp;
      end

      @(negedge clk);
      i_en   = 1'b0;
      i_cnt0 = 1'b0;

      if (rd_sel != 3'b000 && got_rd !== exp_rd) begin
         $display(" [FAIL] %s: a=0x%08X b=0x%08X | Obtido: 0x%08X | Esperado: 0x%08X",
                  op_name, a, b, got_rd, exp_rd);
         errors++;
      end else if (cmp_eq || !cmp_eq) begin
         // Para comparacao, confere flag cmp
         if (last_cmp !== exp_cmp && (cmp_eq || sub)) begin
            $display(" [FAIL] %s: a=0x%08X b=0x%08X | CMP Obtido: %b | CMP Esperado: %b",
                     op_name, a, b, last_cmp, exp_cmp);
            errors++;
         end else begin
            $display(" [PASS] %s: a=0x%08X b=0x%08X -> 0x%08X (cmp=%b)", op_name, a, b, got_rd, last_cmp);
         end
      end
   endtask

   initial begin
      $display("\n========================================================");
      $display(" INICIANDO TESTES UNITARIOS: serv_alu (Tecnologia RTL)");
      $display("========================================================");

      @(posedge clk);
      @(posedge clk);

      // 1. Testes de SOMA (ADD)
      run_op32(32'd10, 32'd20, 1'b0, 2'b00, 3'b001, 1'b0, 1'b0, 32'd30, 1'b0, "ADD simples");
      run_op32(32'h7FFFFFFF, 32'd1, 1'b0, 2'b00, 3'b001, 1'b0, 1'b0, 32'h80000000, 1'b0, "ADD overflow pos");
      run_op32(32'hFFFFFFFF, 32'd1, 1'b0, 2'b00, 3'b001, 1'b0, 1'b0, 32'd0, 1'b0, "ADD wrap zero");
      run_op32(32'h12345678, 32'h87654321, 1'b0, 2'b00, 3'b001, 1'b0, 1'b0, 32'h99999999, 1'b0, "ADD padrao");

      // 2. Testes de SUBTRACAO (SUB)
      run_op32(32'd50, 32'd20, 1'b1, 2'b00, 3'b001, 1'b0, 1'b0, 32'd30, 1'b0, "SUB simples");
      run_op32(32'd10, 32'd20, 1'b1, 2'b00, 3'b001, 1'b0, 1'b0, -32'd10, 1'b1, "SUB negativo");
      run_op32(32'd100, 32'd100, 1'b1, 2'b00, 3'b001, 1'b1, 1'b0, 32'd0, 1'b1, "SUB igualdade (BEQ)");

      // 3. Testes BOOLEANOS
      run_op32(32'hF0F0AA55, 32'h0FF055AA, 1'b0, 2'b00, 3'b100, 1'b0, 1'b0, 32'hFF00FFFF, 1'b0, "XOR");
      run_op32(32'hF0F0AA55, 32'h0F0FAA55, 1'b0, 2'b10, 3'b100, 1'b0, 1'b0, 32'hFFFFAA55, 1'b0, "OR");
      run_op32(32'hF0F0AA55, 32'h0FF055AA, 1'b0, 2'b11, 3'b100, 1'b0, 1'b0, 32'h00F00000, 1'b0, "AND");

      // 4. Testes de COMPARACAO COM SINAL (SLT / BLT)
      run_op32(-32'd10, 32'd5, 1'b1, 2'b00, 3'b000, 1'b0, 1'b1, 32'd0, 1'b1, "SLT (-10 < 5)");
      run_op32(32'd5, -32'd10, 1'b1, 2'b00, 3'b000, 1'b0, 1'b1, 32'd0, 1'b0, "SLT (5 < -10)");

      // 5. Testes de COMPARACAO SEM SINAL (SLTU / BLTU)
      run_op32(32'd5, 32'd10, 1'b1, 2'b00, 3'b000, 1'b0, 1'b0, 32'd0, 1'b1, "SLTU (5 < 10)");
      run_op32(32'hFFFFFFFF, 32'd10, 1'b1, 2'b00, 3'b000, 1'b0, 1'b0, 32'd0, 1'b0, "SLTU (0xFFFFFFFF < 10)");

      $display("========================================================");
      if (errors == 0) begin
         $display(" [SUCESSO] Todos os %0d testes da ALU passaram!", tests_run);
         $display("========================================================\n");
         $finish(0);
      end else begin
         $display(" [FALHA] %0d de %0d testes falharam na ALU!", errors, tests_run);
         $display("========================================================\n");
         $finish(1);
      end
   end
endmodule
