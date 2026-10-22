// serv_bufreg.sv : Registrador de buffer para endereço e dados do SERV em SystemVerilog
module serv_bufreg (
   input  logic        i_clk,
   // Estado
   input  logic        i_cnt0,
   input  logic        i_cnt1,
   input  logic        i_cnt_done,
   input  logic        i_en,
   input  logic        i_init,
   output logic [1:0]  o_lsb,
   // Controle
   input  logic        i_rs1_en,
   input  logic        i_imm_en,
   input  logic        i_clr_lsb,
   input  logic        i_shift_op,
   input  logic        i_right_shift_op,
   input  logic [2:0]  i_shamt,
   input  logic        i_sh_signed,
   // Dados
   input  logic        i_rs1,
   input  logic        i_imm,
   output logic        o_q,
   // Barramento de dados
   output logic [31:0] o_dbus_adr
);

   logic        c;
   logic        q;
   logic        c_r;
   logic [31:0] data;
   logic        clr_lsb;

   assign clr_lsb = i_cnt0 & i_clr_lsb;
   assign {c, q}  = (i_rs1 & i_rs1_en) + (i_imm & i_imm_en & ~clr_lsb) + c_r;

   always_ff @(posedge i_clk) begin
      c_r <= c & i_en;
   end

   always_ff @(posedge i_clk) begin
      if (i_en)
         data[31:2] <= {i_init ? q : (data[31] & i_sh_signed), data[31:3]};

      if (i_init ? (i_cnt0 | i_cnt1) : i_en)
         data[1:0] <= {i_init ? q : data[2], data[1]};
   end

   assign o_lsb = data[1:0];
   assign o_q   = data[0] & i_en;

   assign o_dbus_adr = {data[31:2], 2'b00};

endmodule
