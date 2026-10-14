module sum_fma(input wire [7:0] a, b, c, d,
               output wire [7:0] sum_y, fma_y);
  assign sum_y = (a + b) + c;
  assign fma_y = a * b + d;
endmodule
