module latch_demo(input d, e, en, r, clk, output reg q, output reg qn, output reg q2, output reg qf);
  always @* if (e) q = d;                    // latch, enable ativo alto
  always @* if (!en) qn = d;                 // latch, enable ativo baixo
  always @* if (!r) q2 = 1'b0; else if (e) q2 = d;   // latch com clear
  always @(posedge clk) qf <= d ^ q;         // flip-flop junto
endmodule
