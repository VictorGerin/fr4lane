// serv_rf_ram_if.sv : Interface entre SERV e SRAM síncrona de 2 bits em SystemVerilog
module serv_rf_ram_if #(
   parameter int unsigned width = 2,
   parameter int unsigned csr_regs = 0,
   parameter int unsigned raw = 5,
   parameter int unsigned l2w = 1,
   parameter int unsigned aw = 9
) (
   input  logic            i_clk,
   input  logic            i_rst,
   input  logic            i_wreq,
   input  logic            i_rreq,
   output logic            o_ready,
   input  logic [raw-1:0]  i_wreg0,
   input  logic [raw-1:0]  i_wreg1,
   input  logic            i_wen0,
   input  logic            i_wen1,
   input  logic            i_wdata0,
   input  logic            i_wdata1,
   input  logic [raw-1:0]  i_rreg0,
   input  logic [raw-1:0]  i_rreg1,
   output logic            o_rdata0,
   output logic            o_rdata1,
   // Lado da RAM externa
   output logic [aw-1:0]   o_waddr,
   output logic [width-1:0] o_wdata,
   output logic            o_wen,
   output logic [aw-1:0]   o_raddr,
   output logic            o_ren,
   input  logic [width-1:0] i_rdata
);

   logic        rgnt;
   logic [4:0]  rcnt;
   logic        rtrig1;
   logic [4:0]  wcnt;
   logic [1:0]  wdata0_r;
   logic [2:0]  wdata1_r;
   logic        wen0_r;
   logic        wen1_r;
   logic        wtrig0;
   logic        wtrig1;
   logic [raw-1:0] wreg;

   assign o_ready = rgnt | i_wreq;
   assign wcnt    = rcnt - 5'd4;
   assign wtrig0  = rtrig1;
   assign wtrig1  = wcnt[0];

   assign o_wdata = wtrig1 ? wdata1_r[1:0] : wdata0_r;
   assign wreg    = wtrig1 ? i_wreg1 : i_wreg0;
   assign o_waddr = {wreg, wcnt[4:1]};
   assign o_wen   = (wtrig0 & wen0_r) | (wtrig1 & wen1_r);

   always_ff @(posedge i_clk) begin
      if (wcnt[0]) begin
         wen0_r <= i_wen0;
         wen1_r <= i_wen1;
      end
      wdata0_r <= {i_wdata0, wdata0_r[1]};
      wdata1_r <= {i_wdata1, wdata1_r[2:1]};
   end

   logic        rtrig0;
   logic [raw-1:0] rreg;
   logic [1:0]  rdata0;
   logic        rdata1;
   logic        rgate;
   logic        rreq_r;

   assign rtrig0   = (rcnt[0] == 1'b1);
   assign rreg     = rtrig0 ? i_rreg1 : i_rreg0;
   assign o_raddr  = {rreg, rcnt[4:1]};
   assign o_rdata0 = rdata0[0];
   assign o_rdata1 = rtrig1 ? i_rdata[0] : rdata1;
   assign o_ren    = rgate;

   always_ff @(posedge i_clk) begin
      if (rtrig1)
         rdata1 <= i_rdata[1];

      if (&rcnt | i_rreq)
         rgate <= i_rreq;

      rtrig1 <= rtrig0;
      rcnt <= rcnt + 5'd1;
      if (i_rreq | i_wreq)
         rcnt <= {3'd0, i_wreq, 1'b0};

      rreq_r <= i_rreq;
      rgnt   <= rreq_r;

      rdata0 <= {1'b0, rdata0[1]};
      if (rtrig0)
         rdata0 <= i_rdata;

      if (i_rst) begin
         rgate  <= 1'b0;
         rgnt   <= 1'b0;
         rreq_r <= 1'b0;
         rcnt   <= 5'd0;
      end
   end

endmodule
