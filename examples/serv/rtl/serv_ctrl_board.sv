// serv_ctrl_board.sv : Placa de Controle e Decodificação do SERV em SystemVerilog
//
// Agrupa os módulos de controle do SERV:
//   - serv_state  : Máquina de estados bit-serial e contador de 32 ciclos
//   - serv_decode : Decodificador combinacional de opcodes RV32I
//   - serv_immdec : Decodificador serial de imediatos e registradores
module serv_ctrl_board (
   input  logic        clk,
   input  logic        i_rst,
   // Barramento de instrução (Wishbone)
   input  logic [31:2] i_ibus_rdt,
   input  logic        i_ibus_ack,
   output logic        o_ibus_cyc,
   // Barramento de dados (controle Wishbone)
   output logic        o_dbus_cyc,
   output logic        o_dbus_we,
   input  logic        i_dbus_ack,
   // SRAM do banco de registradores (handshake)
   output logic        o_rf_rreq,
   output logic        o_rf_wreq,
   input  logic        i_rf_ready,
   // Endereços de registradores para o RF
   output logic [4:0]  o_rd_addr,
   output logic [4:0]  o_rs1_addr,
   output logic [4:0]  o_rs2_addr,
   output logic        o_rd_en,
   // Sinais de temporização e ciclo serial para Datapath e PC
   output logic        o_init,
   output logic        o_cnt_en,
   output logic        o_cnt0to3,
   output logic        o_cnt12to31,
   output logic        o_cnt0,
   output logic        o_cnt1,
   output logic        o_cnt2,
   output logic        o_cnt3,
   output logic        o_cnt7,
   output logic        o_cnt11,
   output logic        o_cnt12,
   output logic        o_cnt_done,
   // Controle de PC e Saltos
   output logic        o_ctrl_pc_en,
   output logic        o_ctrl_jump,
   output logic        o_ctrl_jal_or_jalr,
   output logic        o_ctrl_utype,
   output logic        o_ctrl_pc_rel,
   output logic        o_ctrl_mret,
   // Imediatos seriais e controle de buffers
   output logic        o_imm,
   output logic        o_bufreg_en,
   output logic        o_bufreg_rs1_en,
   output logic        o_bufreg_imm_en,
   output logic        o_bufreg_clr_lsb,
   output logic        o_bufreg_sh_signed,
   output logic        o_op_b_sel,
   output logic        o_shift_op,
   output logic        o_sh_right,
   // Controle da ALU
   output logic        o_alu_sub,
   output logic [1:0]  o_alu_bool_op,
   output logic        o_alu_cmp_eq,
   output logic        o_alu_cmp_sig,
   output logic [2:0]  o_alu_rd_sel,
   output logic        o_rd_alu_en,
   // Controle de memória
   output logic        o_mem_signed,
   output logic        o_mem_word,
   output logic        o_mem_half,
   output logic [1:0]  o_mem_bytecnt,
   output logic        o_rd_mem_en,
   // Sinais de feedback vindos das outras placas
   input  logic        i_alu_cmp,
   input  logic        i_sh_done,
   input  logic        i_lsb1,
   input  logic        i_mem_misalign
);

   logic [3:0] immdec_ctrl;
   logic [3:0] immdec_en;
   logic       bne_or_bge;
   logic       cond_branch;
   logic       two_stage_op;
   logic       branch_op;
   logic       rd_op;
   logic       e_op;
   logic       ebreak;
   logic       dbus_en;

   serv_state state (
      .i_clk           (clk),
      .i_rst           (i_rst),
      .i_new_irq       (1'b0),
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
      .o_ctrl_trap     (),
      .i_ctrl_misalign (i_lsb1),
      .i_sh_done       (i_sh_done),
      .o_mem_bytecnt   (o_mem_bytecnt),
      .i_mem_misalign  (i_mem_misalign),
      .i_bne_or_bge    (bne_or_bge),
      .i_cond_branch   (cond_branch),
      .i_dbus_en       (dbus_en),
      .i_two_stage_op  (two_stage_op),
      .i_branch_op     (branch_op),
      .i_shift_op      (o_shift_op),
      .i_sh_right      (o_sh_right),
      .i_alu_rd_sel1   (o_alu_rd_sel[1]),
      .i_rd_alu_en     (o_rd_alu_en),
      .i_e_op          (e_op),
      .i_rd_op         (rd_op),
      .o_dbus_cyc      (o_dbus_cyc),
      .i_dbus_ack      (i_dbus_ack),
      .o_ibus_cyc      (o_ibus_cyc),
      .i_ibus_ack      (i_ibus_ack),
      .o_rf_rreq       (o_rf_rreq),
      .o_rf_wreq       (o_rf_wreq),
      .i_rf_ready      (i_rf_ready),
      .o_rf_rd_en      (o_rd_en)
   );

   serv_decode decode (
      .clk                (clk),
      .i_wb_rdt           (i_ibus_rdt),
      .i_wb_en            (i_ibus_ack),
      .o_bne_or_bge       (bne_or_bge),
      .o_cond_branch      (cond_branch),
      .o_dbus_en          (dbus_en),
      .o_e_op             (e_op),
      .o_ebreak           (ebreak),
      .o_branch_op        (branch_op),
      .o_shift_op         (o_shift_op),
      .o_rd_op            (rd_op),
      .o_sh_right         (o_sh_right),
      .o_two_stage_op     (two_stage_op),
      .o_bufreg_rs1_en    (o_bufreg_rs1_en),
      .o_bufreg_imm_en    (o_bufreg_imm_en),
      .o_bufreg_clr_lsb   (o_bufreg_clr_lsb),
      .o_bufreg_sh_signed (o_bufreg_sh_signed),
      .o_op_b_source      (o_op_b_sel),
      .o_ctrl_jal_or_jalr (o_ctrl_jal_or_jalr),
      .o_ctrl_utype       (o_ctrl_utype),
      .o_ctrl_pc_rel      (o_ctrl_pc_rel),
      .o_ctrl_mret        (o_ctrl_mret),
      .o_alu_sub          (o_alu_sub),
      .o_alu_bool_op      (o_alu_bool_op),
      .o_alu_cmp_eq       (o_alu_cmp_eq),
      .o_alu_cmp_sig      (o_alu_cmp_sig),
      .o_alu_rd_sel       (o_alu_rd_sel),
      .o_mem_cmd          (o_dbus_we),
      .o_mem_signed       (o_mem_signed),
      .o_mem_word         (o_mem_word),
      .o_mem_half         (o_mem_half),
      .o_immdec_ctrl      (immdec_ctrl),
      .o_immdec_en        (immdec_en),
      .o_rd_mem_en        (o_rd_mem_en),
      .o_rd_alu_en        (o_rd_alu_en)
   );

   serv_immdec immdec (
      .i_clk       (clk),
      .i_cnt_en    (o_cnt_en),
      .i_cnt_done  (o_cnt_done),
      .i_immdec_en (immdec_en),
      .i_ctrl      (immdec_ctrl),
      .o_rd_addr   (o_rd_addr),
      .o_rs1_addr  (o_rs1_addr),
      .o_rs2_addr  (o_rs2_addr),
      .o_imm       (o_imm),
      .i_wb_en     (i_ibus_ack),
      .i_wb_rdt    (i_ibus_rdt[31:7])
   );

endmodule
