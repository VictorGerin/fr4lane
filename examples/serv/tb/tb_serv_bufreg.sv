// tb_serv_bufreg.sv : Testbench unitario e vetores de teste para serv_bufreg (Buffer de Endereco/Deslocamento em RTL)
`timescale 1ns/1ps

module tb_serv_bufreg;
   logic        clk = 1'b0;
   always #50 clk = ~clk;

   logic        i_cnt0 = 1'b0;
   logic        i_cnt1 = 1'b0;
   logic        i_cnt_done = 1'b0;
   logic        i_en = 1'b0;
   logic        i_init = 1'b0;
   logic [1:0]  o_lsb;
   logic        i_rs1_en = 1'b1;
   logic        i_imm_en = 1'b1;
   logic        i_clr_lsb = 1'b0;
   logic        i_shift_op = 1'b0;
   logic        i_right_shift_op = 1'b0;
   logic [2:0]  i_shamt = 3'd0;
   logic        i_sh_signed = 1'b0;
   logic        i_rs1 = 1'b0;
   logic        i_imm = 1'b0;
   logic        o_q;
   logic [31:0] o_dbus_adr;

   serv_bufreg dut (
      .i_clk            (clk),
      .i_cnt0           (i_cnt0),
      .i_cnt1           (i_cnt1),
      .i_cnt_done       (i_cnt_done),
      .i_en             (i_en),
      .i_init           (i_init),
      .o_lsb            (o_lsb),
      .i_rs1_en         (i_rs1_en),
      .i_imm_en         (i_imm_en),
      .i_clr_lsb        (i_clr_lsb),
      .i_shift_op       (i_shift_op),
      .i_right_shift_op (i_right_shift_op),
      .i_shamt          (i_shamt),
      .i_sh_signed      (i_sh_signed),
      .i_rs1            (i_rs1),
      .i_imm            (i_imm),
      .o_q              (o_q),
      .o_dbus_adr       (o_dbus_adr)
   );

   integer errors = 0;
   integer tests_run = 0;

   // Tarefa para carregar rs1 + imm (ex: cálculo de endereço de memória)
   task automatic load_addr(
      input [31:0] base_rs1,
      input [31:0] offset_imm,
      input [31:0] exp_adr,
      input [1:0]  exp_lsb,
      input string name
   );
      integer k;
      tests_run++;

      @(negedge clk);
      i_init     = 1'b1;
      i_rs1_en   = 1'b1;
      i_imm_en   = 1'b1;
      i_clr_lsb  = 1'b0;
      i_sh_signed= 1'b0;

      for (k = 0; k < 32; k++) begin
         @(negedge clk);
         i_en   = 1'b1;
         i_cnt0 = (k == 0);
         i_cnt1 = (k == 1);
         i_cnt_done = (k == 31);
         i_rs1  = base_rs1[k];
         i_imm  = offset_imm[k];
         @(posedge clk);
      end

      @(negedge clk);
      i_en   = 1'b0;
      i_init = 1'b0;
      i_cnt0 = 1'b0;
      i_cnt1 = 1'b0;
      i_cnt_done = 1'b0;
      #1;

      if (o_dbus_adr !== exp_adr || o_lsb !== exp_lsb) begin
         $display(" [FAIL] %s: dbus_adr=0x%08X (exp 0x%08X) lsb=%b (exp %b)",
                  name, o_dbus_adr, exp_adr, o_lsb, exp_lsb);
         errors++;
      end else begin
         $display(" [PASS] %s: Endereco alinhado = 0x%08X, LSB = %b", name, o_dbus_adr, o_lsb);
      end
   endtask

   initial begin
      $display("\n========================================================");
      $display(" INICIANDO TESTES UNITARIOS: serv_bufreg (Buffer em RTL)");
      $display("========================================================");

      repeat (2) @(posedge clk);

      // 1. Calculo de endereco alinhado: base 0x1000 + offset 0x0020 = 0x1020, lsb=00
      load_addr(32'h0000_1000, 32'h0000_0020, 32'h0000_1020, 2'b00, "Endereco alinhado 0x1020");

      // 2. Calculo com offset desalinhado: base 0x2000 + offset 0x0003 = 0x2000 (adr), lsb=11
      load_addr(32'h0000_2000, 32'h0000_0003, 32'h0000_2000, 2'b11, "Endereco desalinhado 0x2003");

      // 3. Calculo com carry: base 0x00FF + offset 0x0002 = 0x0100 (adr), lsb=01
      load_addr(32'h0000_00FF, 32'h0000_0002, 32'h0000_0100, 2'b01, "Endereco com carry 0x0101");

      $display("========================================================");
      if (errors == 0) begin
         $display(" [SUCESSO] Todos os %0d testes de serv_bufreg passaram!", tests_run);
         $display("========================================================\n");
         $finish(0);
      end else begin
         $display(" [FALHA] %0d de %0d testes falharam em serv_bufreg!", errors, tests_run);
         $display("========================================================\n");
         $finish(1);
      end
   end
endmodule
