// tb_serv_state.sv : Testbench unitario e vetores de teste para serv_state (FSM de Controle em RTL)
`timescale 1ns/1ps

module tb_serv_state;
   logic       clk = 1'b0;
   always #50 clk = ~clk;

   logic       i_rst = 1'b1;
   logic       i_new_irq = 1'b0;
   logic       i_alu_cmp = 1'b0;
   logic       o_init;
   logic       o_cnt_en;
   logic       o_cnt0to3;
   logic       o_cnt12to31;
   logic       o_cnt0;
   logic       o_cnt1;
   logic       o_cnt2;
   logic       o_cnt3;
   logic       o_cnt7;
   logic       o_cnt11;
   logic       o_cnt12;
   logic       o_cnt_done;
   logic       o_bufreg_en;
   logic       o_ctrl_pc_en;
   logic       o_ctrl_jump;
   logic       o_ctrl_trap;
   logic       i_ctrl_misalign = 1'b0;
   logic       i_sh_done = 1'b0;
   logic [1:0] o_mem_bytecnt;
   logic       i_mem_misalign = 1'b0;
   logic       i_bne_or_bge = 1'b0;
   logic       i_cond_branch = 1'b0;
   logic       i_dbus_en = 1'b0;
   logic       i_two_stage_op = 1'b0;
   logic       i_branch_op = 1'b0;
   logic       i_shift_op = 1'b0;
   logic       i_sh_right = 1'b0;
   logic       i_alu_rd_sel1 = 1'b0;
   logic       i_rd_alu_en = 1'b0;
   logic       i_e_op = 1'b0;
   logic       i_rd_op = 1'b1;
   output logic o_dbus_cyc;
   logic       i_dbus_ack = 1'b0;
   logic       o_ibus_cyc;
   logic       i_ibus_ack = 1'b0;
   logic       o_rf_rreq;
   logic       o_rf_wreq;
   logic       i_rf_ready = 1'b0;
   logic       o_rf_rd_en;

   serv_state dut (
      .i_clk           (clk),
      .i_rst           (i_rst),
      .i_new_irq       (i_new_irq),
      .i_alu_cmp       (i_alu_cmp),
      .o_init          (o_init),
      .o_cnt_en        (o_cnt_en),
      .o_cnt0to3       (o_cnt0to3),
      .o_cnt12to31     (o_cnt12to31),
      .o_cnt0          (o_cnt0),
      .o_cnt1          (o_cnt1),
      .o_cnt2          (o_cnt2),
      .o_cnt3          (o_cnt3),
      .o_cnt7          (o_cnt7),
      .o_cnt11         (o_cnt11),
      .o_cnt12         (o_cnt12),
      .o_cnt_done      (o_cnt_done),
      .o_bufreg_en     (o_bufreg_en),
      .o_ctrl_pc_en    (o_ctrl_pc_en),
      .o_ctrl_jump     (o_ctrl_jump),
      .o_ctrl_trap     (o_ctrl_trap),
      .i_ctrl_misalign (i_ctrl_misalign),
      .i_sh_done       (i_sh_done),
      .o_mem_bytecnt   (o_mem_bytecnt),
      .i_mem_misalign  (i_mem_misalign),
      .i_bne_or_bge    (i_bne_or_bge),
      .i_cond_branch   (i_cond_branch),
      .i_dbus_en       (i_dbus_en),
      .i_two_stage_op  (i_two_stage_op),
      .i_branch_op     (i_branch_op),
      .i_shift_op      (i_shift_op),
      .i_sh_right      (i_sh_right),
      .i_alu_rd_sel1   (i_alu_rd_sel1),
      .i_rd_alu_en     (i_rd_alu_en),
      .i_e_op          (i_e_op),
      .i_rd_op         (i_rd_op),
      .o_dbus_cyc      (o_dbus_cyc),
      .i_dbus_ack      (i_dbus_ack),
      .o_ibus_cyc      (o_ibus_cyc),
      .i_ibus_ack      (i_ibus_ack),
      .o_rf_rreq       (o_rf_rreq),
      .o_rf_wreq       (o_rf_wreq),
      .i_rf_ready      (i_rf_ready),
      .o_rf_rd_en      (o_rf_rd_en)
   );

   integer errors = 0;
   integer tests_run = 0;

   initial begin
      integer cyc_count;
      $display("\n========================================================");
      $display(" INICIANDO TESTES UNITARIOS: serv_state (FSM de Controle em RTL)");
      $display("========================================================");

      // 1. Reset
      repeat (3) @(posedge clk);
      @(negedge clk);
      i_rst = 1'b0;
      @(posedge clk);

      tests_run++;
      if (o_cnt_en !== 1'b0 || o_ibus_cyc !== 1'b1) begin
         $display(" [FAIL] Reset: cnt_en=%b (exp 0) ibus_cyc=%b (exp 1)", o_cnt_en, o_ibus_cyc);
         errors++;
      end else begin
         $display(" [PASS] Reset correto: ocioso e aguardando instrucao (ibus_cyc=1)");
      end

      // 2. Disparo de instrucao de 1 estagio (ADD / OP / OP-IMM)
      i_two_stage_op = 1'b0;
      @(negedge clk);
      i_rf_ready = 1'b1; // RF pronto dispara contagem
      @(negedge clk);
      i_rf_ready = 1'b0;

      cyc_count = 0;
      while (o_cnt_en && cyc_count < 40) begin
         if (cyc_count == 0 && !o_cnt0) begin
            $display(" [FAIL] Ciclo 0: o_cnt0 deveria ser 1");
            errors++;
         end
         if (cyc_count == 1 && !o_cnt1) begin
            $display(" [FAIL] Ciclo 1: o_cnt1 deveria ser 1");
            errors++;
         end
         if (cyc_count == 2 && !o_cnt2) begin
            $display(" [FAIL] Ciclo 2: o_cnt2 deveria ser 1");
            errors++;
         end
         if (cyc_count == 31 && !o_cnt_done) begin
            $display(" [FAIL] Ciclo 31: o_cnt_done deveria ser 1");
            errors++;
         end
         cyc_count++;
         @(negedge clk);
      end

      tests_run++;
      if (cyc_count !== 32) begin
         $display(" [FAIL] Contagem de ciclos: %0d (esperado exatamente 32)", cyc_count);
         errors++;
      end else begin
         $display(" [PASS] Ciclo serial executou exatamente 32 clocks com temporizacao precisa!");
      end

      // 3. Instrucao de 2 estagios (Branch ou Shift)
      repeat (2) @(negedge clk);
      i_two_stage_op = 1'b1;
      i_branch_op    = 1'b1;
      i_cond_branch  = 1'b1;
      i_alu_cmp      = 1'b1; // Condicao de branch verdadeira!
      i_bne_or_bge   = 1'b0;
      i_rf_ready     = 1'b1;
      @(negedge clk);
      i_rf_ready     = 1'b0;

      // Estagio 1: o_init deve ser 1
      tests_run++;
      if (!o_init) begin
         $display(" [FAIL] Estagio 1: o_init deveria ser 1");
         errors++;
      end else begin
         $display(" [PASS] Estagio 1 iniciado: o_init = 1");
      end

      // Aguarda o_cnt_done no ciclo 31
      while (!o_cnt_done) @(negedge clk);
      // No ciclo seguinte a o_cnt_done, o_ctrl_jump deve estar ativo
      @(negedge clk);

      // Confere se o_ctrl_jump foi ativado no final do estagio 1
      tests_run++;
      if (!o_ctrl_jump) begin
         $display(" [FAIL] o_ctrl_jump deveria ter sido ativado para branch! (jump=%b)", o_ctrl_jump);
         errors++;
      end else begin
         $display(" [PASS] Branch tomado: o_ctrl_jump ativado corretamente!");
      end

      $display("========================================================");
      if (errors == 0) begin
         $display(" [SUCESSO] Todos os %0d testes da FSM de controle passaram!", tests_run);
         $display("========================================================\n");
         $finish(0);
      end else begin
         $display(" [FALHA] %0d de %0d testes falharam em serv_state!", errors, tests_run);
         $display("========================================================\n");
         $finish(1);
      end
   end
endmodule
