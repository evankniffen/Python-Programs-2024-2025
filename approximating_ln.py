# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 6.15
# Date:         9 - 25 - 2024
#
from math import *
x = float(input("Enter a value for x: "))
if x <= 0 or x > 2:
    while x <= 0 or x > 2:
        x = float(input("Out of range! Try again: "))
tol = float(input("Enter the tolerance: "))
approx = 0.0
real = log(x)
n = 1
val = -(1 - x) ** n / n 
#evaluating the approximation
while abs(val) > tol:
    approx += val
    n += 1
    val = -(1 - x) ** n / n 
if x == 2.0 :
    approx += val
print(f"ln({x}) is approximately {approx}")
print(f"ln({x}) is exactly {real}")
print("The difference is",abs(real - approx))