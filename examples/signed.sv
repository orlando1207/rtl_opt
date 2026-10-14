module signed_example(input wire signed [7:0] a, b,
                      input wire [3:0] shift,
                      output wire signed [15:0] y,
                      output wire lt);
  assign y = $signed(a) >>> shift;
  assign lt = a < b;
endmodule
