// Reconstruction benchmark, not the original author's FIR source.
module fir3(input wire [7:0] x0, x1, x2, output wire [15:0] y);
  assign y = 16'd3 * {8'b0, x0} + 16'd7 * {8'b0, x1} + 16'd21 * {8'b0, x2};
endmodule
