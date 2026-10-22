// tb_serv_ctrl.sv : Testbench unitario e vetores de teste para serv_ctrl (Program Counter em RTL)
`timescale 1ns/1ps

module tb_serv_ctrl;
   localparam int PC_WIDTH = 13;
   localparam [31:0] RESET_PC = 32'h0000_0000;

   logic        clk = 1'b0;
   always #50 clk = ~clk;

   logic        i_rst = 1'b1;
   logic        i_pc_en = 1'b0;
   logic        i_cnt12to31 = 1'b0;
   logic        i_cnt0 = 1'b0;
   logic        i_cnt1 = 1'b0;
   logic        i_cnt2 = 1'b0;
   logic        i_jump = 1'b0;
   logic        i_jal_or_jalr = 1'b0;
   logic        i_utype = 1'b0;
   logic        i_pc_rel = 1'b0;
   logic        i_imm = 1'b0;
   logic        i_buf = 1'b0;
   logic        o_rd;
   logic        o_bad_pc;
   logic [31:0] o_ibus_adr;

   serv_ctrl dut (
      .clk          (clk),
      .i_rst        (i_rst),
      .i_pc_en      (i_pc_en),
      .i_cnt12to31  (i_cnt12to31),
      .i_cnt0       (i_cnt0),
      .i_cnt1       (i_cnt1),
      .i_cnt2       (i_cnt2),
      .i_jump       (i_jump),
      .i_jal_or_jalr(i_jal_or_jalr),
      .i_utype      (i_utype),
      .i_pc_rel     (i_pc_rel),
      .i_imm        (i_imm),
      .i_buf        (i_buf),
      .o_rd         (o_rd),
      .o_bad_pc     (o_bad_pc),
      .o_ibus_adr   (o_ibus_adr)
   );

   integer errors = 0;
   integer tests_run = 0;

   // Executa 32 ciclos para atualizar o PC (ou avançar PC + 4, ou pular)
   task automatic step_pc(
      input        jump,
      input        jal_or_jalr,
      input        utype,
      input        pc_rel,
      input [31:0] buf_data,
      input [31:0] exp_pc,
      input string desc
   );
      logic [31:0] got_rd;
      integer k;

      tests_run++;
      got_rd = 32'd0;

      @(negedge clk);
      i_jump        = jump;
      i_jal_or_jalr = jal_or_jalr;
      i_utype       = utype;
      i_pc_rel      = pc_rel;
      i_imm         = 1'b0;

      for (k = 0; k < 32; k++) begin
         @(negedge clk);
         i_pc_en     = 1'b1;
         i_cnt0      = (k == 0);
         i_cnt1      = (k == 1);
         i_cnt2      = (k == 2);
         i_cnt12to31 = (k >= 12);
         i_buf       = buf_data[k];
         @(posedge clk);
         got_rd[k] = o_rd;
      end

      @(negedge clk);
      i_pc_en = 1'b0;
      i_cnt0  = 1'b0;
      i_cnt1  = 1'b0;
      i_cnt2  = 1'b0;
      i_cnt12to31 = 1'b0;

      if (o_ibus_adr !== exp_pc) begin
         $display(" [FAIL] %s: PC Obtido: 0x%08X | Esperado: 0x%08X", desc, o_ibus_adr, exp_pc);
         errors++;
      end else begin
         $display(" [PASS] %s: PC = 0x%08X", desc, o_ibus_adr);
      end
   endtask

   initial begin
      $display("\n========================================================");
      $display(" INICIANDO TESTES UNITARIOS: serv_ctrl (Program Counter em RTL)");
      $display("========================================================");

      // 1. Reset
      repeat (3) @(posedge clk);
      @(negedge clk);
      i_rst = 1'b0;
      @(posedge clk);

      tests_run++;
      if (o_ibus_adr !== RESET_PC) begin
         $display(" [FAIL] Reset: PC inicial = 0x%08X (esperado: 0x%08X)", o_ibus_adr, RESET_PC);
         errors++;
      end else begin
         $display(" [PASS] Reset correto: PC = 0x%08X", o_ibus_adr);
      end

      // 2. Incrementos normais (PC + 4)
      step_pc(1'b0, 1'b0, 1'b0, 1'b0, 32'd0, 32'h0000_0004, "Incremento PC+4 #1");
      step_pc(1'b0, 1'b0, 1'b0, 1'b0, 32'd0, 32'h0000_0008, "Incremento PC+4 #2");
      step_pc(1'b0, 1'b0, 1'b0, 1'b0, 32'd0, 32'h0000_000C, "Incremento PC+4 #3");
      step_pc(1'b0, 1'b0, 1'b0, 1'b0, 32'd0, 32'h0000_0010, "Incremento PC+4 #4");

      // 3. Salto relativo (Branch/JAL): PC = 0x0010 + 0x0020 = 0x0030
      step_pc(1'b1, 1'b0, 1'b0, 1'b1, 32'h0000_0020, 32'h0000_0030, "Salto relativo (+32)");

      // 4. Salto relativo para tras (Branch negativo): PC = 0x0030 - 0x0010 = 0x0020
      step_pc(1'b1, 1'b0, 1'b0, 1'b1, -32'd16, 32'h0000_0020, "Salto relativo (-16)");

      // 5. Salto absoluto (JALR): PC = 0x0000_0100
      step_pc(1'b1, 1'b1, 1'b0, 1'b0, 32'h0000_0100, 32'h0000_0100, "Salto absoluto JALR (0x100)");

      // 6. Mais incrementos apos o salto
      step_pc(1'b0, 1'b0, 1'b0, 1'b0, 32'd0, 32'h0000_0104, "Incremento pos-salto (0x104)");

      $display("========================================================");
      if (errors == 0) begin
         $display(" [SUCESSO] Todos os %0d testes do Program Counter passaram!", tests_run);
         $display("========================================================\n");
         $finish(0);
      end else begin
         $display(" [FALHA] %0d de %0d testes falharam no Program Counter!", errors, tests_run);
         $display("========================================================\n");
         $finish(1);
      end
   end
endmodule
