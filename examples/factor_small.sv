module factor_small(input wire [3:0] a, b, c, output wire [3:0] y);
  assign y = a * b + a * c;
endmodule
