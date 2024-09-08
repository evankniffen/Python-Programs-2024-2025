# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 4.21
# Date:         9 - 05 - 2024
#
from math import *
# finds the quadratic roots.
A = float(input("Please enter the coefficient A: "))
B = float(input("Please enter the coefficient B: "))
C = float(input("Please enter the coefficient C: "))
disc = B ** 2 - 4 * A * C
if A == 0 :
    if B == 0:
        print("You entered an invalid combination of coefficients!")
    else:
        sol3 = -C / B
        print("The root is x =",sol3)
else:
    if disc == 0 :
        # 1 solution 
        sol1 = (-B + sqrt(disc)) / (2 * A)
        print("The root is x =",sol1)
    elif disc > 0 :
        # 2 real solutions
        sol1 = (-B + sqrt(disc)) / (2 * A)
        sol2 = (-B - sqrt(disc)) / (2 * A)
        print("The roots are x =",sol1,"and x =",sol2)
    else :
        # 2 imaginary solutions
        realSol = -B / (2 * A)
        compSol = sqrt(abs(disc)) / (2 * A)
        sol1 = str(realSol) + " + " + str(compSol) + "i"
        sol2 = str(realSol) + " - " + str(compSol) + "i"
        if A < 0 :
            temp = sol1
            sol1 = sol2
            sol2 = temp
        print("The roots are x =",sol1,"and x =",sol2)