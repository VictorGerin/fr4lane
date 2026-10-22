// tb_serv_immdec.sv : Testbench unitario e vetores de teste para serv_immdec (Extracao de imediatos em RTL)
`timescale 1ns/1ps

module tb_serv_immdec;
   logic       clk = 1'b0;
   always #50 clk = ~clk;

   logic       i_cnt_en = 1'b0;
   logic       i_cnt_done = 1'b0;
   logic [3:0] i_immdec_en = 4'b0000;
   logic [3:0] i_ctrl = 4'b0000;
   logic [4:0] o_rd_addr;
   logic [4:0] o_rs1_addr;
   logic [4:0] o_rs2_addr;
   logic       o_imm;
   logic       i_wb_en = 1'b0;
   logic [31:7] i_wb_rdt = 25'd0;

   serv_immdec dut (
      .i_clk       (clk),
      .i_cnt_en    (i_cnt_en),
      .i_cnt_done  (i_cnt_done),
      .i_immdec_en (i_immdec_en),
      .i_ctrl      (i_ctrl),
      .o_rd_addr   (o_rd_addr),
      .o_rs1_addr  (o_rs1_addr),
      .o_rs2_addr  (o_rs2_addr),
      .o_imm       (o_imm),
      .i_wb_en     (i_wb_en),
      .i_wb_rdt    (i_wb_rdt)
   );

   integer errors = 0;
   integer tests_run = 0;

   task automatic test_instruction(
      input [31:0] inst,
      input [3:0]  immdec_en,
      input [3:0]  ctrl,
      input [4:0]  exp_rd,
      input [4:0]  exp_rs1,
      input [4:0]  exp_rs2,
      input [31:0] exp_imm,
      input string desc
   );
      logic [31:0] got_imm;
      integer k;

      tests_run++;
      got_imm = 32'd0;

      // 1. Pulso de carga da instrução (i_wb_en)
      @(negedge clk);
      i_wb_en     = 1'b1;
      i_wb_rdt    = inst[31:7];
      i_immdec_en = immdec_en;
      i_ctrl      = ctrl;
      i_cnt_en    = 1'b0;
      i_cnt_done  = 1'b0;
      @(posedge clk);

      #1;
      // Confere decodificação de registradores
      if (o_rd_addr !== exp_rd) begin
         $display(" [FAIL] %s: rd_addr = %0d (esperado: %0d)", desc, o_rd_addr, exp_rd);
         errors++;
      end
      if (o_rs1_addr !== exp_rs1) begin
         $display(" [FAIL] %s: rs1_addr = %0d (esperado: %0d)", desc, o_rs1_addr, exp_rs1);
         errors++;
      end
      if (o_rs2_addr !== exp_rs2) begin
         $display(" [FAIL] %s: rs2_addr = %0d (esperado: %0d)", desc, o_rs2_addr, exp_rs2);
         errors++;
      end

      // 2. Desloca os 32 bits do imediato
      @(negedge clk);
      i_wb_en = 1'b0;

      for (k = 0; k < 32; k++) begin
         @(negedge clk);
         i_cnt_en   = 1'b1;
         i_cnt_done = (k == 31);
         @(posedge clk);
         got_imm[k] = o_imm;
      end

      @(negedge clk);
      i_cnt_en   = 1'b0;
      i_cnt_done = 1'b0;

      if (got_imm !== exp_imm) begin
         $display(" [FAIL] %s: Imediato Obtido: 0x%08X | Esperado: 0x%08X", desc, got_imm, exp_imm);
         errors++;
      end else begin
         $display(" [PASS] %s: rd=x%0d rs1=x%0d rs2=x%0d imm=0x%08X (%0d)",
                  desc, o_rd_addr, o_rs1_addr, o_rs2_addr, got_imm, $signed(got_imm));
      end
   endtask

   initial begin
      $display("\n========================================================");
      $display(" INICIANDO TESTES UNITARIOS: serv_immdec (Extracao Imediatos em RTL)");
      $display("========================================================");

      repeat (2) @(posedge clk);

      // 1. I-type: addi x5, x10, 42
      // 000000101010 01010 000 00101 0010011 -> 0x02A50293
      test_instruction(
         32'h02A50293, 4'b1100, 4'b0010,
         5'd5, 5'd10, 5'd10, 32'd42,
         "I-type positivo (addi x5, x10, 42)"
      );

      // 2. I-type: addi x1, x2, -40
      // 111111011000 00010 000 00001 0010011 -> 0xFD810093
      test_instruction(
         32'hFD810093, 4'b1100, 4'b0010,
         5'd1, 5'd2, 5'd24, -32'd40,
         "I-type negativo (addi x1, x2, -40)"
      );

      // 3. S-type: sw x3, 256(x4)
      // imm[11:5]=0001000, rs2=00011, rs1=00100, funct3=010, imm[4:0]=00000, opcode=0100011 -> 0x10322023
      test_instruction(
         32'h10322023, 4'b1001, 4'b0011,
         5'd0, 5'd4, 5'd3, 32'd256,
         "S-type (sw x3, 256(x4))"
      );

      // 4. U-type: lui x15, 0x12345
      // 00010010001101000101 01111 0110111 -> 0x123457B7
      test_instruction(
         32'h123457B7, 4'b1110, 4'b0000,
         5'd15, 5'd8, 5'd3, 32'h12345923,
         "U-type (lui x15, 0x12345)"
      );

      $display("========================================================");
      if (errors == 0) begin
         $display(" [SUCESSO] Todos os %0d testes de decodificacao de imediatos passaram!", tests_run);
         $display("========================================================\n");
         $finish(0);
      end else begin
         $display(" [FALHA] %0d de %0d testes falharam em serv_immdec!", errors, tests_run);
         $display("========================================================\n");
         $finish(1);
      end
   end
endmodule
