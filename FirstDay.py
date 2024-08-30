from math import *
from sympy import *

print("Howdy, World!")  

x = Symbol('x')
y = Symbol('y')
print(integrate(exp(sqrt(-1)*x), (x,1,10)))
