`timescale 1ns/1ps
module tb_latch_demo;
  reg d, e, en, r, clk; wire q, qn, q2, qf;
  latch_demo dut(.d(d), .e(e), .en(en), .r(r), .clk(clk), .q(q), .qn(qn), .q2(q2), .qf(qf));
  integer k, fails; reg mq, mqn, mq2, mqf;
  initial begin
    fails = 0; clk = 0; r = 0; e = 1; en = 0; d = 0; #20; r = 1; #20;
    mq = 0; mqn = 0; mq2 = 0; mqf = 1'bx;
    for (k = 0; k < 300; k = k + 1) begin
      d = $random; #20;
      if (e) mq = d; if (!en) mqn = d; if (!r) mq2 = 0; else if (e) mq2 = d;
      if (q !== mq || qn !== mqn || q2 !== mq2) begin fails = fails + 1; $display("ERROR k=%0d", k); end
      case ($random & 3) 0: e = ~e; 1: en = ~en; 2: r = ($random & 3) != 0; 3: ; endcase
      #20;
      if (e) mq = d; if (!en) mqn = d; if (!r) mq2 = 0; else if (e) mq2 = d;
      if (q !== mq || qn !== mqn || q2 !== mq2) begin fails = fails + 1; $display("ERROR2 k=%0d", k); end
      clk = 1; #20; clk = 0; #20;
    end
    if (fails == 0) $display("PASS"); else $display("FAILED %0d", fails);
    $finish;
  end
endmodule
