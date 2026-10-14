module mux_mul(input wire [7:0] a, b, c, input wire sel, output wire [7:0] y);
  assign y = sel ? a * b : a * c;
endmodule
