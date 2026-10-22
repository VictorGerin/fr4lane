// serv_top.sv : Conexão dos submódulos do SERV em SystemVerilog
module serv_top #(
   parameter bit [31:0] RESET_PC = 32'd0
) (
   input  logic        clk,
   input  logic        i_rst,
   // Interface do banco de registradores (RF)
   output logic        o_rf_rreq,
   output logic        o_rf_wreq,
   input  logic        i_rf_ready,
   output logic [4:0]  o_wreg0,
   output logic [4:0]  o_wreg1,
   output logic        o_wen0,
   output logic        o_wen1,
   output logic        o_wdata0,
   output logic        o_wdata1,
   output logic [4:0]  o_rreg0,
   output logic [4:0]  o_rreg1,
   input  logic        i_rdata0,
   input  logic        i_rdata1,
   // Barramento de instrução (Wishbone)
   output logic [31:0] o_ibus_adr,
   output logic        o_ibus_cyc,
   input  logic [31:0] i_ibus_rdt,
   input  logic        i_ibus_ack,
   // Barramento de dados (Wishbone)
   output logic [31:0] o_dbus_adr,
   output logic [31:0] o_dbus_dat,
   output logic [3:0]  o_dbus_sel,
   output logic        o_dbus_we,
   output logic        o_dbus_cyc,
   input  logic [31:0] i_dbus_rdt,
   input  logic        i_dbus_ack
);

   logic [4:0]  rd_addr;
   logic [4:0]  rs1_addr;
   logic [4:0]  rs2_addr;
   logic [3:0]  immdec_ctrl;
   logic [3:0]  immdec_en;
   logic        sh_right;
   logic        bne_or_bge;
   logic        cond_branch;
   logic        two_stage_op;
   logic        e_op;
   logic        ebreak;
   logic        branch_op;
   logic        shift_op;
   logic        rd_op;
   logic        rd_alu_en;
   logic        rd_mem_en;
   logic        ctrl_rd;
   logic        alu_rd;
   logic        mem_rd;
   logic        ctrl_pc_en;
   logic        jump;
   logic        jal_or_jalr;
   logic        utype;
   logic        mret;
   logic        imm;
   logic        pc_rel;
   logic        init;
   logic        cnt_en;
   logic        cnt0to3;
   logic        cnt12to31;
   logic        cnt0;
   logic        cnt1;
   logic        cnt2;
   logic        cnt3;
   logic        cnt7;
   logic        cnt11;
   logic        cnt12;
   logic        cnt_done;
   logic        bufreg_en;
   logic        bufreg_sh_signed;
   logic        bufreg_rs1_en;
   logic        bufreg_imm_en;
   logic        bufreg_clr_lsb;
   logic        bufreg_q;
   logic        bufreg2_q;
   logic        alu_sub;
   logic [1:0]  alu_bool_op;
   logic        alu_cmp_eq;
   logic        alu_cmp_sig;
   logic        alu_cmp;
   logic [2:0]  alu_rd_sel;
   logic        rs1;
   logic        rs2;
   logic        rd_en;
   logic        op_b;
   logic        op_b_sel;
   logic        mem_signed;
   logic        mem_word;
   logic        mem_half;
   logic [1:0]  mem_bytecnt;
   logic        sh_done;
   logic        mem_misalign;
   logic        bad_pc;
   logic        dbus_en;
   logic [1:0]  lsb;

   serv_state state (
      .i_clk           (clk),
      .i_rst           (i_rst),
      .i_new_irq       (1'b0),
      .i_alu_cmp       (alu_cmp),
      .o_init          (init),
      .o_cnt_en        (cnt_en),
      .o_cnt0to3       (cnt0to3),
      .o_cnt12to31     (cnt12to31),
      .o_cnt0          (cnt0),
      .o_cnt1          (cnt1),
      .o_cnt2          (cnt2),
      .o_cnt3          (cnt3),
      .o_cnt7          (cnt7),
      .o_cnt11         (cnt11),
      .o_cnt12         (cnt12),
      .o_cnt_done      (cnt_done),
      .o_bufreg_en     (bufreg_en),
      .o_ctrl_pc_en    (ctrl_pc_en),
      .o_ctrl_jump     (jump),
      .o_ctrl_trap     (),
      .i_ctrl_misalign (lsb[1]),
      .i_sh_done       (sh_done),
      .o_mem_bytecnt   (mem_bytecnt),
      .i_mem_misalign  (mem_misalign),
      .i_bne_or_bge    (bne_or_bge),
      .i_cond_branch   (cond_branch),
      .i_dbus_en       (dbus_en),
      .i_two_stage_op  (two_stage_op),
      .i_branch_op     (branch_op),
      .i_shift_op      (shift_op),
      .i_sh_right      (sh_right),
      .i_alu_rd_sel1   (alu_rd_sel[1]),
      .i_rd_alu_en     (rd_alu_en),
      .i_e_op          (e_op),
      .i_rd_op         (rd_op),
      .o_dbus_cyc      (o_dbus_cyc),
      .i_dbus_ack      (i_dbus_ack),
      .o_ibus_cyc      (o_ibus_cyc),
      .i_ibus_ack      (i_ibus_ack),
      .o_rf_rreq       (o_rf_rreq),
      .o_rf_wreq       (o_rf_wreq),
      .i_rf_ready      (i_rf_ready),
      .o_rf_rd_en      (rd_en)
   );

   serv_decode decode (
      .clk                (clk),
      .i_wb_rdt           (i_ibus_rdt[31:2]),
      .i_wb_en            (i_ibus_ack),
      .o_bne_or_bge       (bne_or_bge),
      .o_cond_branch      (cond_branch),
      .o_dbus_en          (dbus_en),
      .o_e_op             (e_op),
      .o_ebreak           (ebreak),
      .o_branch_op        (branch_op),
      .o_shift_op         (shift_op),
      .o_rd_op            (rd_op),
      .o_sh_right         (sh_right),
      .o_two_stage_op     (two_stage_op),
      .o_bufreg_rs1_en    (bufreg_rs1_en),
      .o_bufreg_imm_en    (bufreg_imm_en),
      .o_bufreg_clr_lsb   (bufreg_clr_lsb),
      .o_bufreg_sh_signed (bufreg_sh_signed),
      .o_op_b_source      (op_b_sel),
      .o_ctrl_jal_or_jalr (jal_or_jalr),
      .o_ctrl_utype       (utype),
      .o_ctrl_pc_rel      (pc_rel),
      .o_ctrl_mret        (mret),
      .o_alu_sub          (alu_sub),
      .o_alu_bool_op      (alu_bool_op),
      .o_alu_cmp_eq       (alu_cmp_eq),
      .o_alu_cmp_sig      (alu_cmp_sig),
      .o_alu_rd_sel       (alu_rd_sel),
      .o_mem_cmd          (o_dbus_we),
      .o_mem_signed       (mem_signed),
      .o_mem_word         (mem_word),
      .o_mem_half         (mem_half),
      .o_immdec_ctrl      (immdec_ctrl),
      .o_immdec_en        (immdec_en),
      .o_rd_mem_en        (rd_mem_en),
      .o_rd_alu_en        (rd_alu_en)
   );

   serv_immdec immdec (
      .i_clk       (clk),
      .i_cnt_en    (cnt_en),
      .i_cnt_done  (cnt_done),
      .i_immdec_en (immdec_en),
      .i_ctrl      (immdec_ctrl),
      .o_rd_addr   (rd_addr),
      .o_rs1_addr  (rs1_addr),
      .o_rs2_addr  (rs2_addr),
      .o_imm       (imm),
      .i_wb_en     (i_ibus_ack),
      .i_wb_rdt    (i_ibus_rdt[31:7])
   );

   serv_bufreg bufreg (
      .i_clk            (clk),
      .i_cnt0           (cnt0),
      .i_cnt1           (cnt1),
      .i_cnt_done       (cnt_done),
      .i_en             (bufreg_en),
      .i_init           (init),
      .o_lsb            (lsb),
      .i_sh_signed      (bufreg_sh_signed),
      .i_rs1_en         (bufreg_rs1_en),
      .i_imm_en         (bufreg_imm_en),
      .i_clr_lsb        (bufreg_clr_lsb),
      .i_shift_op       (shift_op),
      .i_right_shift_op (sh_right),
      .i_shamt          (o_dbus_dat[26:24]),
      .i_rs1            (rs1),
      .i_imm            (imm),
      .o_q              (bufreg_q),
      .o_dbus_adr       (o_dbus_adr)
   );

   serv_bufreg2 bufreg2 (
      .i_clk      (clk),
      .i_en       (cnt_en),
      .i_init     (init),
      .i_cnt7     (cnt7),
      .i_cnt_done (cnt_done),
      .i_sh_right (sh_right),
      .i_lsb      (lsb),
      .i_bytecnt  (mem_bytecnt),
      .o_sh_done  (sh_done),
      .i_op_b_sel (op_b_sel),
      .i_shift_op (shift_op),
      .i_rs2      (rs2),
      .i_imm      (imm),
      .o_op_b     (op_b),
      .o_q        (bufreg2_q),
      .o_dat      (o_dbus_dat),
      .i_load     (i_dbus_ack),
      .i_dat      (i_dbus_rdt)
   );

   serv_ctrl #(
      .RESET_PC (RESET_PC)
   ) ctrl (
      .clk           (clk),
      .i_rst         (i_rst),
      .i_pc_en       (ctrl_pc_en),
      .i_cnt12to31   (cnt12to31),
      .i_cnt0        (cnt0),
      .i_cnt1        (cnt1),
      .i_cnt2        (cnt2),
      .i_jump        (jump),
      .i_jal_or_jalr (jal_or_jalr),
      .i_utype       (utype),
      .i_pc_rel      (pc_rel),
      .i_imm         (imm),
      .i_buf         (bufreg_q),
      .o_rd          (ctrl_rd),
      .o_bad_pc      (bad_pc),
      .o_ibus_adr    (o_ibus_adr)
   );

   serv_alu alu (
      .clk       (clk),
      .i_en      (cnt_en),
      .i_cnt0    (cnt0),
      .o_cmp     (alu_cmp),
      .i_sub     (alu_sub),
      .i_bool_op (alu_bool_op),
      .i_cmp_eq  (alu_cmp_eq),
      .i_cmp_sig (alu_cmp_sig),
      .i_rd_sel  (alu_rd_sel),
      .i_rs1     (rs1),
      .i_op_b    (op_b),
      .i_buf     (bufreg_q),
      .o_rd      (alu_rd)
   );

   serv_rf_if rf_if (
      .i_cnt_en    (cnt_en),
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
      .i_rd_wen    (rd_en),
      .i_rd_waddr  (rd_addr),
      .i_ctrl_rd   (ctrl_rd),
      .i_alu_rd    (alu_rd),
      .i_rd_alu_en (rd_alu_en),
      .i_mem_rd    (mem_rd),
      .i_rd_mem_en (rd_mem_en),
      .i_rs1_raddr (rs1_addr),
      .o_rs1       (rs1),
      .i_rs2_raddr (rs2_addr),
      .o_rs2       (rs2)
   );

   serv_mem_if mem_if (
      .i_clk       (clk),
      .i_bytecnt   (mem_bytecnt),
      .i_lsb       (lsb),
      .o_misalign  (mem_misalign),
      .i_signed    (mem_signed),
      .i_word      (mem_word),
      .i_half      (mem_half),
      .i_bufreg2_q (bufreg2_q),
      .o_rd        (mem_rd),
      .o_wb_sel    (o_dbus_sel)
   );

endmodule
