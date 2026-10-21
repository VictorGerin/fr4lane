// Máquina de estados de controle de bomba d'água de um tanque com 2 sensores:
//   nivel_baixo (1 = água acima do sensor inferior, 0 = abaixo)
//   nivel_alto  (1 = água atingiu o sensor superior, 0 = abaixo)
//
// 4 estados em ciclo:
//   VAZIO      (2'b00): bomba desligada; com o tanque vazio (!nivel_baixo), passa a ENCHENDO
//   ENCHENDO   (2'b01): bomba ligada até atingir o sensor superior (nivel_alto -> CHEIO)
//   CHEIO      (2'b10): bomba desligada; quando o nível desce do topo (!nivel_alto -> ESVAZIANDO)
//   ESVAZIANDO (2'b11): bomba desligada até esvaziar abaixo do sensor inferior (!nivel_baixo -> VAZIO)
module tanque (
    input            clk,
    input            rst_n,
    input            nivel_baixo,
    input            nivel_alto,
    output reg [1:0] estado,
    output           bomba
);
    localparam [1:0] VAZIO      = 2'b00,
                     ENCHENDO   = 2'b01,
                     CHEIO      = 2'b10,
                     ESVAZIANDO = 2'b11;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            estado <= VAZIO;
        else begin
            case (estado)
                VAZIO:      if (!nivel_baixo) estado <= ENCHENDO;
                ENCHENDO:   if (nivel_alto)   estado <= CHEIO;
                CHEIO:      if (!nivel_alto)  estado <= ESVAZIANDO;
                ESVAZIANDO: if (!nivel_baixo) estado <= VAZIO;
                default:    estado <= VAZIO;
            endcase
        end
    end

    assign bomba = (estado == ENCHENDO);
endmodule
