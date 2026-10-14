module mcm(input wire [7:0] x, output wire [7:0] y3, y7, y21);
  assign y3 = 8'd3 * x;
  assign y7 = 8'd7 * x;
  assign y21 = 8'd21 * x;
endmodule
