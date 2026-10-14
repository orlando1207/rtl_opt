module truncation(input wire [7:0] a, b, c, output wire [8:0] y);
  wire [7:0] t;
  assign t = a + b;
  assign y = {1'b0, t} + {1'b0, c};
endmodule
