// serv_system.sv : Sistema multi-placa do SERV (Top / Backplane) em SystemVerilog
//
// Conecta a pilha de 4 placas que compõem o processador RISC-V RV32I bit-serial:
//   - u_ctrl   (serv_ctrl_board)   : FSM de controle, decodificador e imediatos (~3.500 comp.)
//   - u_pc     (serv_pc_board)     : Program Counter e somador de branch/jal (~1.900 comp.)
//   - u_alu    (serv_alu_board)    : ALU serial de 1 bit e registradores bufreg (~4.600 comp.)
//   - u_rf_mem (serv_rf_mem_board) : Banco de registradores e alinhamento de memória (~1.400 comp.)
module serv_system #(
   parameter int        PC_WIDTH = 13,
   parameter bit [31:0] RESET_PC = 32'd0,
   parameter            RESET_STRATEGY = "MINI",
   parameter bit        WITH_CSR = 1'b0,
   parameter bit        WITH_E = 1'b0,
   parameter int        WREG = WITH_E ? 4 : 5,
   parameter int        AW_RF = WITH_E ? 8 : 9
) (
   input  logic                clk,
   input  logic                i_rst,

   // Barramento do sistema (ibus + dbus + rf unificados em struct aninhada)
   output serv_pkg::sys_req_t  o_sys,
   input  serv_pkg::sys_rsp_t  i_sys
);

   // Sinais internos dos barramentos externos
   logic [31:0]      o_ibus_adr;
   logic             o_ibus_cyc;
   logic [31:0]      o_dbus_adr;
   logic [31:0]      o_dbus_dat;
   logic [3:0]       o_dbus_sel;
   logic             o_dbus_we;
   logic             o_dbus_cyc;
   logic [AW_RF-1:0] o_rf_waddr_raw;
   logic [1:0]       o_rf_wdata_raw;
   logic             o_rf_wen_raw;
   logic [AW_RF-1:0] o_rf_raddr_raw;
   logic             o_rf_ren_raw;

   assign o_sys.ibus.adr = o_ibus_adr;
   assign o_sys.ibus.cyc = o_ibus_cyc;

   assign o_sys.dbus.adr = o_dbus_adr;
   assign o_sys.dbus.dat = o_dbus_dat;
   assign o_sys.dbus.sel = o_dbus_sel;
   assign o_sys.dbus.we  = o_dbus_we;
   assign o_sys.dbus.cyc = o_dbus_cyc;

   assign o_sys.rf.waddr = { {(9-AW_RF){1'b0}}, o_rf_waddr_raw };
   assign o_sys.rf.wdata = o_rf_wdata_raw;
   assign o_sys.rf.wen   = o_rf_wen_raw;
   assign o_sys.rf.raddr = { {(9-AW_RF){1'b0}}, o_rf_raddr_raw };
   assign o_sys.rf.ren   = o_rf_ren_raw;

   // Barramento de empilhamento (J_STACK): Union packed com structs aninhadas
   serv_pkg::j_stack_t stack;

   // Sinais de endereço com largura parametrizada WREG
   logic [WREG-1:0] rd_addr;
   logic [WREG-1:0] rs1_addr;
   logic [WREG-1:0] rs2_addr;

   assign stack.signals.rf.rd_addr  = { {(5-WREG){1'b0}}, rd_addr };
   assign stack.signals.rf.rs1_addr = { {(5-WREG){1'b0}}, rs1_addr };
   assign stack.signals.rf.rs2_addr = { {(5-WREG){1'b0}}, rs2_addr };

   serv_ctrl_board #(
      .WITH_E (WITH_E)
   ) u_ctrl (
      .clk                (clk),
      .i_rst              (i_rst),
      .i_ibus_rdt         (i_sys.ibus.rdt[31:2]),
      .i_ibus_ack         (i_sys.ibus.ack),
      .o_ibus_cyc         (o_ibus_cyc),
      .o_dbus_cyc         (o_dbus_cyc),
      .o_dbus_we          (o_dbus_we),
      .i_dbus_ack         (i_sys.dbus.ack),
      .o_rf_rreq          (),
      .o_rf_wreq          (stack.signals.rf.rf_wreq),
      .i_rf_ready         (stack.signals.rf.rf_ready),
      .o_rd_addr          (rd_addr),
      .o_rs1_addr         (rs1_addr),
      .o_rs2_addr         (rs2_addr),
      .o_rd_en            (stack.signals.ctrl.rd_en),
      .o_init             (stack.signals.timing.init),
      .o_cnt_en           (stack.signals.timing.cnt_en),
      .o_cnt0to3          (stack.signals.timing.cnt0to3),
      .o_cnt12to31        (stack.signals.timing.cnt12to31),
      .o_cnt0             (stack.signals.timing.cnt0),
      .o_cnt1             (stack.signals.timing.cnt1),
      .o_cnt2             (stack.signals.timing.cnt2),
      .o_cnt3             (stack.signals.timing.cnt3),
      .o_cnt7             (stack.signals.timing.cnt7),
      .o_cnt11            (stack.signals.timing.cnt11),
      .o_cnt12            (stack.signals.timing.cnt12),
      .o_cnt_done         (stack.signals.timing.cnt_done),
      .o_ctrl_pc_en       (stack.signals.ctrl.pc_en),
      .o_ctrl_jump        (stack.signals.ctrl.jump),
      .o_ctrl_jal_or_jalr (stack.signals.ctrl.jal_or_jalr),
      .o_ctrl_utype       (stack.signals.ctrl.utype),
      .o_ctrl_pc_rel      (stack.signals.ctrl.pc_rel),
      .o_ctrl_mret        (stack.signals.ctrl.mret),
      .o_imm              (stack.signals.data.imm),
      .o_bufreg_en        (stack.signals.bufreg.en),
      .o_bufreg_rs1_en    (stack.signals.bufreg.rs1_en),
      .o_bufreg_imm_en    (stack.signals.bufreg.imm_en),
      .o_bufreg_clr_lsb   (stack.signals.bufreg.clr_lsb),
      .o_bufreg_sh_signed (stack.signals.bufreg.sh_signed),
      .o_op_b_sel         (stack.signals.alu.op_b_sel),
      .o_shift_op         (stack.signals.alu.shift_op),
      .o_sh_right         (stack.signals.alu.sh_right),
      .o_alu_sub          (stack.signals.alu.sub),
      .o_alu_bool_op      (stack.signals.alu.bool_op),
      .o_alu_cmp_eq       (stack.signals.alu.cmp_eq),
      .o_alu_cmp_sig      (stack.signals.alu.cmp_sig),
      .o_alu_rd_sel       (stack.signals.alu.rd_sel),
      .o_rd_alu_en        (stack.signals.ctrl.rd_alu_en),
      .o_mem_signed       (stack.signals.mem.signed_op),
      .o_mem_word         (stack.signals.mem.word_op),
      .o_mem_half         (stack.signals.mem.half_op),
      .o_mem_bytecnt      (stack.signals.mem.bytecnt),
      .o_rd_mem_en        (stack.signals.ctrl.rd_mem_en),
      .i_alu_cmp          (stack.signals.data.alu_cmp),
      .i_sh_done          (stack.signals.data.sh_done),
      .i_lsb1             (stack.signals.data.lsb[1]),
      .i_mem_misalign     (1'b0)
   );

   serv_pc_board #(
      .PC_WIDTH (PC_WIDTH),
      .RESET_PC (RESET_PC)
   ) u_pc (
      .clk           (clk),
      .i_rst         (i_rst),
      .i_pc_en       (stack.signals.ctrl.pc_en),
      .i_cnt12to31   (stack.signals.timing.cnt12to31),
      .i_cnt0        (stack.signals.timing.cnt0),
      .i_cnt1        (stack.signals.timing.cnt1),
      .i_cnt2        (stack.signals.timing.cnt2),
      .i_jump        (stack.signals.ctrl.jump),
      .i_jal_or_jalr (stack.signals.ctrl.jal_or_jalr),
      .i_utype       (stack.signals.ctrl.utype),
      .i_pc_rel      (stack.signals.ctrl.pc_rel),
      .i_imm         (stack.signals.data.imm),
      .i_bufreg_q    (stack.signals.data.bufreg_q),
      .o_ctrl_rd     (stack.signals.data.ctrl_rd),
      .o_bad_pc      (),
      .o_ibus_adr    (o_ibus_adr)
   );

   serv_alu_board u_alu (
      .clk                (clk),
      .i_cnt_en           (stack.signals.timing.cnt_en),
      .i_cnt0             (stack.signals.timing.cnt0),
      .i_cnt1             (stack.signals.timing.cnt1),
      .i_cnt7             (stack.signals.timing.cnt7),
      .i_cnt_done         (stack.signals.timing.cnt_done),
      .i_init             (stack.signals.timing.init),
      .i_alu_sub          (stack.signals.alu.sub),
      .i_alu_bool_op      (stack.signals.alu.bool_op),
      .i_alu_cmp_eq       (stack.signals.alu.cmp_eq),
      .i_alu_cmp_sig      (stack.signals.alu.cmp_sig),
      .i_alu_rd_sel       (stack.signals.alu.rd_sel),
      .i_bufreg_en        (stack.signals.bufreg.en),
      .i_bufreg_rs1_en    (stack.signals.bufreg.rs1_en),
      .i_bufreg_imm_en    (stack.signals.bufreg.imm_en),
      .i_bufreg_clr_lsb   (stack.signals.bufreg.clr_lsb),
      .i_bufreg_sh_signed (stack.signals.bufreg.sh_signed),
      .i_op_b_sel         (stack.signals.alu.op_b_sel),
      .i_shift_op         (stack.signals.alu.shift_op),
      .i_sh_right         (stack.signals.alu.sh_right),
      .i_rs1              (stack.signals.data.rs1),
      .i_rs2              (stack.signals.data.rs2),
      .i_imm              (stack.signals.data.imm),
      .i_mem_bytecnt      (stack.signals.mem.bytecnt),
      .o_alu_rd           (stack.signals.data.alu_rd),
      .o_alu_cmp          (stack.signals.data.alu_cmp),
      .o_sh_done          (stack.signals.data.sh_done),
      .o_lsb              (stack.signals.data.lsb),
      .o_bufreg_q         (stack.signals.data.bufreg_q),
      .o_bufreg2_q        (stack.signals.data.bufreg2_q),
      .o_dbus_adr         (o_dbus_adr),
      .o_dbus_dat         (o_dbus_dat),
      .i_dbus_rdt         (i_sys.dbus.rdt),
      .i_dbus_ack         (i_sys.dbus.ack)
   );

   serv_rf_mem_board #(
      .WITH_E (WITH_E)
   ) u_rf_mem (
      .clk            (clk),
      .i_rst          (i_rst),
      .i_cnt_en       (stack.signals.timing.cnt_en),
      .i_bytecnt      (stack.signals.mem.bytecnt),
      .i_lsb          (stack.signals.data.lsb),
      .i_rf_rreq      (i_sys.ibus.ack),
      .i_rf_wreq      (stack.signals.rf.rf_wreq),
      .o_rf_ready     (stack.signals.rf.rf_ready),
      .i_rd_addr      (rd_addr),
      .i_rs1_addr     (rs1_addr),
      .i_rs2_addr     (rs2_addr),
      .i_rd_en        (stack.signals.ctrl.rd_en),
      .i_ctrl_rd      (stack.signals.data.ctrl_rd),
      .i_alu_rd       (stack.signals.data.alu_rd),
      .i_rd_alu_en    (stack.signals.ctrl.rd_alu_en),
      .i_rd_mem_en    (stack.signals.ctrl.rd_mem_en),
      .i_mem_signed   (stack.signals.mem.signed_op),
      .i_mem_word     (stack.signals.mem.word_op),
      .i_mem_half     (stack.signals.mem.half_op),
      .i_bufreg2_q    (stack.signals.data.bufreg2_q),
      .o_rs1          (stack.signals.data.rs1),
      .o_rs2          (stack.signals.data.rs2),
      .o_mem_misalign (),
      .o_dbus_sel     (o_dbus_sel),
      .o_rf_waddr     (o_rf_waddr_raw),
      .o_rf_wdata     (o_rf_wdata_raw),
      .o_rf_wen       (o_rf_wen_raw),
      .o_rf_raddr     (o_rf_raddr_raw),
      .o_rf_ren       (o_rf_ren_raw),
      .i_rf_rdata     (i_sys.rf.rdata)
   );

endmodule
