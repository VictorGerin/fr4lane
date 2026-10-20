// Controle: contador de passos (T0 a T4) e microcódigo. No original, o
// microcódigo fica em EEPROMs; aqui ele vira lógica combinacional.
import sap1_pkg::*;

module sap1_control (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    run,      // 0: parado (programação)
    input  logic [3:0]              opcode,
    input  logic                    cf,
    input  logic                    zf,
    output sap1_pkg::ctrl_t         cw
);
    sap1_pkg::step_t step;

    // O HLT congela o contador de passos: a CPU fica no T2 do HLT.
    always_ff @(posedge clk or negedge rst_n)
        if (!rst_n)
            step <= T0;
        else if (run && !cw.hlt)
            case (step)
                T0:      step <= T1;
                T1:      step <= T2;
                T2:      step <= T3;
                T3:      step <= T4;
                default: step <= T0;
            endcase

    always_comb begin
        cw = '0;
        if (run)
            case (step)
                T0: begin cw.co = 1; cw.mi = 1; end                   // busca
                T1: begin cw.ro = 1; cw.ii = 1; cw.ce = 1; end
                T2: case (opcode)
                    LDA, ADD, SUB, STA:
                         begin cw.io = 1;  cw.mi = 1;  end
                    LDI: begin cw.io = 1;  cw.ai = 1;  end
                    JMP: begin cw.io = 1;  cw.j  = 1;  end
                    JC:  begin cw.io = cf; cw.j  = cf; end
                    JZ:  begin cw.io = zf; cw.j  = zf; end
                    OUT: begin cw.ao = 1;  cw.oi = 1;  end
                    HLT: cw.hlt = 1;
                    default: ;                                       // NOP
                endcase
                T3: case (opcode)
                    LDA:      begin cw.ro = 1; cw.ai = 1; end
                    ADD, SUB: begin cw.ro = 1; cw.bi = 1; end
                    STA:      begin cw.ao = 1; cw.ri = 1; end
                    default: ;
                endcase
                T4: case (opcode)
                    ADD: begin cw.eo = 1; cw.ai = 1; cw.fi = 1; end
                    SUB: begin cw.eo = 1; cw.ai = 1; cw.fi = 1; cw.su = 1; end
                    default: ;
                endcase
                default: ;
            endcase
    end
endmodule
