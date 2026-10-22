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

   // 1. Barramento de Instruções (Wishbone)
   output serv_pkg::ibus_req_t o_ibus,
   input  serv_pkg::ibus_rsp_t i_ibus,

   // 2. Barramento de Dados (Wishbone)
   output serv_pkg::dbus_req_t o_dbus,
   input  serv_pkg::dbus_rsp_t i_dbus,

   // 3. SRAM externa do banco de registradores (rf)
   output serv_pkg::rf_req_t   o_rf,
   input  serv_pkg::rf_rsp_t   i_rf
);

   // Sinais internos dos barramentos
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

   assign o_ibus.adr = o_ibus_adr;
   assign o_ibus.cyc = o_ibus_cyc;

   assign o_dbus.adr = o_dbus_adr;
   assign o_dbus.dat = o_dbus_dat;
   assign o_dbus.sel = o_dbus_sel;
   assign o_dbus.we  = o_dbus_we;
   assign o_dbus.cyc = o_dbus_cyc;

   assign o_rf.waddr = { {(9-AW_RF){1'b0}}, o_rf_waddr_raw };
   assign o_rf.wdata = o_rf_wdata_raw;
   assign o_rf.wen   = o_rf_wen_raw;
   assign o_rf.raddr = { {(9-AW_RF){1'b0}}, o_rf_raddr_raw };
   assign o_rf.ren   = o_rf_ren_raw;

   // Sinais da pilha de conexões (Header comum J_STACK)
   logic       init;
   logic       cnt_en;
   logic       cnt0to3;
   logic       cnt12to31;
   logic       cnt0;
   logic       cnt1;
   logic       cnt2;
   logic       cnt3;
   logic       cnt7;
   logic       cnt11;
   logic       cnt12;
   logic       cnt_done;

   logic       ctrl_pc_en;
   logic       ctrl_jump;
   logic       ctrl_jal_or_jalr;
   logic       ctrl_utype;
   logic       ctrl_pc_rel;
   logic       ctrl_mret;
   logic       ctrl_rd;
   logic       bad_pc;

   logic       imm;
   logic       bufreg_en;
   logic       bufreg_rs1_en;
   logic       bufreg_imm_en;
   logic       bufreg_clr_lsb;
   logic       bufreg_sh_signed;
   logic       op_b_sel;
   logic       shift_op;
   logic       sh_right;
   logic       bufreg_q;
   logic       bufreg2_q;
   logic       sh_done;
   logic [1:0] lsb;

   logic       alu_sub;
   logic [1:0] alu_bool_op;
   logic       alu_cmp_eq;
   logic       alu_cmp_sig;
   logic [2:0] alu_rd_sel;
   logic       rd_alu_en;
   logic       alu_rd;
   logic       alu_cmp;

   logic       mem_signed;
   logic       mem_word;
   logic       mem_half;
   logic [1:0] mem_bytecnt;
   logic       rd_mem_en;
   logic       mem_misalign;

   logic [WREG-1:0] rd_addr;
   logic [WREG-1:0] rs1_addr;
   logic [WREG-1:0] rs2_addr;
   logic       rd_en;
   logic       rs1;
   logic       rs2;
   logic       rf_rreq;
   logic       rf_wreq;
   logic       rf_ready;

   serv_ctrl_board #(
      .WITH_E (WITH_E)
   ) u_ctrl (
      .clk                (clk),
      .i_rst              (i_rst),
      .i_ibus_rdt         (i_ibus.rdt[31:2]),
      .i_ibus_ack         (i_ibus.ack),
      .o_ibus_cyc         (o_ibus_cyc),
      .o_dbus_cyc         (o_dbus_cyc),
      .o_dbus_we          (o_dbus_we),
      .i_dbus_ack         (i_dbus.ack),
      .o_rf_rreq          (),
      .o_rf_wreq          (rf_wreq),
      .i_rf_ready         (rf_ready),
      .o_rd_addr          (rd_addr),
      .o_rs1_addr         (rs1_addr),
      .o_rs2_addr         (rs2_addr),
      .o_rd_en            (rd_en),
      .o_init             (init),
      .o_cnt_en           (cnt_en),
      .o_cnt0to3          (cnt0to3),
      .o_cnt12to31        (cnt12to31),
      .o_cnt0             (cnt0),
      .o_cnt1             (cnt1),
      .o_cnt2             (cnt2),
      .o_cnt3             (cnt3),
      .o_cnt7             (cnt7),
      .o_cnt11            (cnt11),
      .o_cnt12            (cnt12),
      .o_cnt_done         (cnt_done),
      .o_ctrl_pc_en       (ctrl_pc_en),
      .o_ctrl_jump        (ctrl_jump),
      .o_ctrl_jal_or_jalr (ctrl_jal_or_jalr),
      .o_ctrl_utype       (ctrl_utype),
      .o_ctrl_pc_rel      (ctrl_pc_rel),
      .o_ctrl_mret        (ctrl_mret),
      .o_imm              (imm),
      .o_bufreg_en        (bufreg_en),
      .o_bufreg_rs1_en    (bufreg_rs1_en),
      .o_bufreg_imm_en    (bufreg_imm_en),
      .o_bufreg_clr_lsb   (bufreg_clr_lsb),
      .o_bufreg_sh_signed (bufreg_sh_signed),
      .o_op_b_sel         (op_b_sel),
      .o_shift_op         (shift_op),
      .o_sh_right         (sh_right),
      .o_alu_sub          (alu_sub),
      .o_alu_bool_op      (alu_bool_op),
      .o_alu_cmp_eq       (alu_cmp_eq),
      .o_alu_cmp_sig      (alu_cmp_sig),
      .o_alu_rd_sel       (alu_rd_sel),
      .o_rd_alu_en        (rd_alu_en),
      .o_mem_signed       (mem_signed),
      .o_mem_word         (mem_word),
      .o_mem_half         (mem_half),
      .o_mem_bytecnt      (mem_bytecnt),
      .o_rd_mem_en        (rd_mem_en),
      .i_alu_cmp          (alu_cmp),
      .i_sh_done          (sh_done),
      .i_lsb1             (lsb[1]),
      .i_mem_misalign     (1'b0)
   );

   serv_pc_board #(
      .PC_WIDTH (PC_WIDTH),
      .RESET_PC (RESET_PC)
   ) u_pc (
      .clk           (clk),
      .i_rst         (i_rst),
      .i_pc_en       (ctrl_pc_en),
      .i_cnt12to31   (cnt12to31),
      .i_cnt0        (cnt0),
      .i_cnt1        (cnt1),
      .i_cnt2        (cnt2),
      .i_jump        (ctrl_jump),
      .i_jal_or_jalr (ctrl_jal_or_jalr),
      .i_utype       (ctrl_utype),
      .i_pc_rel      (ctrl_pc_rel),
      .i_imm         (imm),
      .i_bufreg_q    (bufreg_q),
      .o_ctrl_rd     (ctrl_rd),
      .o_bad_pc      (bad_pc),
      .o_ibus_adr    (o_ibus_adr)
   );

   serv_alu_board u_alu (
      .clk                (clk),
      .i_cnt_en           (cnt_en),
      .i_cnt0             (cnt0),
      .i_cnt1             (cnt1),
      .i_cnt7             (cnt7),
      .i_cnt_done         (cnt_done),
      .i_init             (init),
      .i_alu_sub          (alu_sub),
      .i_alu_bool_op      (alu_bool_op),
      .i_alu_cmp_eq       (alu_cmp_eq),
      .i_alu_cmp_sig      (alu_cmp_sig),
      .i_alu_rd_sel       (alu_rd_sel),
      .i_bufreg_en        (bufreg_en),
      .i_bufreg_rs1_en    (bufreg_rs1_en),
      .i_bufreg_imm_en    (bufreg_imm_en),
      .i_bufreg_clr_lsb   (bufreg_clr_lsb),
      .i_bufreg_sh_signed (bufreg_sh_signed),
      .i_op_b_sel         (op_b_sel),
      .i_shift_op         (shift_op),
      .i_sh_right         (sh_right),
      .i_rs1              (rs1),
      .i_rs2              (rs2),
      .i_imm              (imm),
      .i_mem_bytecnt      (mem_bytecnt),
      .o_alu_rd           (alu_rd),
      .o_alu_cmp          (alu_cmp),
      .o_sh_done          (sh_done),
      .o_lsb              (lsb),
      .o_bufreg_q         (bufreg_q),
      .o_bufreg2_q        (bufreg2_q),
      .o_dbus_adr         (o_dbus_adr),
      .o_dbus_dat         (o_dbus_dat),
      .i_dbus_rdt         (i_dbus.rdt),
      .i_dbus_ack         (i_dbus.ack)
   );

   serv_rf_mem_board #(
      .WITH_E (WITH_E)
   ) u_rf_mem (
      .clk            (clk),
      .i_rst          (i_rst),
      .i_cnt_en       (cnt_en),
      .i_bytecnt      (mem_bytecnt),
      .i_lsb          (lsb),
      .i_rf_rreq      (i_ibus.ack),
      .i_rf_wreq      (rf_wreq),
      .o_rf_ready     (rf_ready),
      .i_rd_addr      (rd_addr),
      .i_rs1_addr     (rs1_addr),
      .i_rs2_addr     (rs2_addr),
      .i_rd_en        (rd_en),
      .i_ctrl_rd      (ctrl_rd),
      .i_alu_rd       (alu_rd),
      .i_rd_alu_en    (rd_alu_en),
      .i_rd_mem_en    (rd_mem_en),
      .i_mem_signed   (mem_signed),
      .i_mem_word     (mem_word),
      .i_mem_half     (mem_half),
      .i_bufreg2_q    (bufreg2_q),
      .o_rs1          (rs1),
      .o_rs2          (rs2),
      .o_mem_misalign (),
      .o_dbus_sel     (o_dbus_sel),
      .o_rf_waddr     (o_rf_waddr_raw),
      .o_rf_wdata     (o_rf_wdata_raw),
      .o_rf_wen       (o_rf_wen_raw),
      .o_rf_raddr     (o_rf_raddr_raw),
      .o_rf_ren       (o_rf_ren_raw),
      .i_rf_rdata     (i_rf.rdata)
   );

endmodule
