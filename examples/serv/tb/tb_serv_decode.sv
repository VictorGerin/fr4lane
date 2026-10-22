// tb_serv_decode.sv : Testbench unitario e vetores de teste para serv_decode (Decodificador de Instrucoes em RTL)
`timescale 1ns/1ps

module tb_serv_decode;
   logic        clk = 1'b0;
   always #50 clk = ~clk;

   logic [31:2] i_wb_rdt = 30'd0;
   logic        i_wb_en = 1'b0;

   // Sinais decodificados
   logic        o_sh_right;
   logic        o_bne_or_bge;
   logic        o_cond_branch;
   logic        o_e_op;
   logic        o_ebreak;
   logic        o_branch_op;
   logic        o_shift_op;
   logic        o_rd_op;
   logic        o_two_stage_op;
   logic        o_dbus_en;
   logic        o_bufreg_rs1_en;
   logic        o_bufreg_imm_en;
   logic        o_bufreg_clr_lsb;
   logic        o_bufreg_sh_signed;
   logic        o_ctrl_jal_or_jalr;
   logic        o_ctrl_utype;
   logic        o_ctrl_pc_rel;
   logic        o_ctrl_mret;
   logic        o_alu_sub;
   logic [1:0]  o_alu_bool_op;
   logic        o_alu_cmp_eq;
   logic        o_alu_cmp_sig;
   logic [2:0]  o_alu_rd_sel;
   logic        o_mem_signed;
   logic        o_mem_word;
   logic        o_mem_half;
   logic        o_mem_cmd;
   logic [3:0]  o_immdec_ctrl;
   logic [3:0]  o_immdec_en;
   logic        o_op_b_source;
   logic        o_rd_mem_en;
   logic        o_rd_alu_en;

   serv_decode dut (
      .clk                (clk),
      .i_wb_rdt           (i_wb_rdt),
      .i_wb_en            (i_wb_en),
      .o_sh_right         (o_sh_right),
      .o_bne_or_bge       (o_bne_or_bge),
      .o_cond_branch      (o_cond_branch),
      .o_e_op             (o_e_op),
      .o_ebreak           (o_ebreak),
      .o_branch_op        (o_branch_op),
      .o_shift_op         (o_shift_op),
      .o_rd_op            (o_rd_op),
      .o_two_stage_op     (o_two_stage_op),
      .o_dbus_en          (o_dbus_en),
      .o_bufreg_rs1_en    (o_bufreg_rs1_en),
      .o_bufreg_imm_en    (o_bufreg_imm_en),
      .o_bufreg_clr_lsb   (o_bufreg_clr_lsb),
      .o_bufreg_sh_signed (o_bufreg_sh_signed),
      .o_ctrl_jal_or_jalr (o_ctrl_jal_or_jalr),
      .o_ctrl_utype       (o_ctrl_utype),
      .o_ctrl_pc_rel      (o_ctrl_pc_rel),
      .o_ctrl_mret        (o_ctrl_mret),
      .o_alu_sub          (o_alu_sub),
      .o_alu_bool_op      (o_alu_bool_op),
      .o_alu_cmp_eq       (o_alu_cmp_eq),
      .o_alu_cmp_sig      (o_alu_cmp_sig),
      .o_alu_rd_sel       (o_alu_rd_sel),
      .o_mem_signed       (o_mem_signed),
      .o_mem_word         (o_mem_word),
      .o_mem_half         (o_mem_half),
      .o_mem_cmd          (o_mem_cmd),
      .o_immdec_ctrl      (o_immdec_ctrl),
      .o_immdec_en        (o_immdec_en),
      .o_op_b_source      (o_op_b_source),
      .o_rd_mem_en        (o_rd_mem_en),
      .o_rd_alu_en        (o_rd_alu_en)
   );

   integer errors = 0;
   integer tests_run = 0;

   task automatic decode_check(
      input [31:0] inst,
      input        exp_rd_alu,
      input        exp_rd_mem,
      input        exp_dbus,
      input        exp_branch,
      input        exp_jal,
      input [2:0]  exp_alu_sel,
      input        exp_alu_sub,
      input string name
   );
      tests_run++;

      @(negedge clk);
      i_wb_en  = 1'b1;
      i_wb_rdt = inst[31:2];
      @(posedge clk);

      #1;
      @(negedge clk);
      i_wb_en  = 1'b0;
      #1;

      if (o_rd_alu_en !== exp_rd_alu ||
          o_rd_mem_en !== exp_rd_mem ||
          o_dbus_en   !== exp_dbus   ||
          o_branch_op !== exp_branch ||
          o_ctrl_jal_or_jalr !== exp_jal ||
          o_alu_rd_sel !== exp_alu_sel ||
          o_alu_sub !== exp_alu_sub) begin
         $display(" [FAIL] %s (inst=0x%08X):", name, inst);
         $display("        rd_alu=%b (exp %b) rd_mem=%b (exp %b) dbus=%b (exp %b)",
                  o_rd_alu_en, exp_rd_alu, o_rd_mem_en, exp_rd_mem, o_dbus_en, exp_dbus);
         $display("        branch=%b (exp %b) jal=%b (exp %b) alu_sel=%b (exp %b) sub=%b (exp %b)",
                  o_branch_op, exp_branch, o_ctrl_jal_or_jalr, exp_jal, o_alu_rd_sel, exp_alu_sel, o_alu_sub, exp_alu_sub);
         errors++;
      end else begin
         $display(" [PASS] %s: Decodificado perfeitamente (inst=0x%08X)", name, inst);
      end
   endtask

   initial begin
      $display("\n========================================================");
      $display(" INICIANDO TESTES UNITARIOS: serv_decode (Decodificador em RTL)");
      $display("========================================================");

      repeat (2) @(posedge clk);

      // 1. ADDI (OP-IMM, rd_alu=1, alu_sel=001, sub=0)
      decode_check(32'h02A50293, 1'b1, 1'b0, 1'b0, 1'b0, 1'b0, 3'b001, 1'b0, "ADDI");

      // 2. ADD (OP, rd_alu=1, alu_sel=001, sub=0)
      decode_check(32'h002080B3, 1'b1, 1'b0, 1'b0, 1'b0, 1'b0, 3'b001, 1'b0, "ADD");

      // 3. SUB (OP com funct7[5]=1, rd_alu=1, alu_sel=001, sub=1)
      decode_check(32'h402080B3, 1'b1, 1'b0, 1'b0, 1'b0, 1'b0, 3'b001, 1'b1, "SUB");

      // 4. AND (OP com funct3=111, rd_alu=1, alu_sel=100)
      decode_check(32'h0020F0B3, 1'b1, 1'b0, 1'b0, 1'b0, 1'b0, 3'b100, 1'b1, "AND");

      // 5. LW (LOAD, dbus=1, rd_mem=1, rd_alu=0)
      decode_check(32'h00012083, 1'b0, 1'b1, 1'b1, 1'b0, 1'b0, 3'b010, 1'b1, "LW");

      // 6. SW (STORE, dbus=1, rd_mem=1, rd_alu=0)
      decode_check(32'h0020A023, 1'b0, 1'b1, 1'b1, 1'b0, 1'b0, 3'b010, 1'b1, "SW");

      // 7. BEQ (BRANCH, branch=1, cond=1, jal=0)
      decode_check(32'h00208463, 1'b0, 1'b1, 1'b0, 1'b1, 1'b0, 3'b001, 1'b1, "BEQ");

      // 8. JAL (JUMP, jal=1, branch=1)
      decode_check(32'h0000006F, 1'b0, 1'b0, 1'b0, 1'b1, 1'b1, 3'b001, 1'b1, "JAL");

      $display("========================================================");
      if (errors == 0) begin
         $display(" [SUCESSO] Todos os %0d testes de decodificacao passaram!", tests_run);
         $display("========================================================\n");
         $finish(0);
      end else begin
         $display(" [FALHA] %0d de %0d testes falharam em serv_decode!", errors, tests_run);
         $display("========================================================\n");
         $finish(1);
      end
   end
endmodule
