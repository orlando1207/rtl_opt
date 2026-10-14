module factor(input wire [7:0] a, b, c, output wire [7:0] y);
  assign y = a * b + a * c;
endmodule
