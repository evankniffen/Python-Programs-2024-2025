# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 3.3
# Date:         8 - 28 - 2024
#
from math import *
# allowing for user inputs
digs = int(input("Please enter the number of digits of precision for tau: "))
roundTau = (((tau * (10 ** digs)) + .5) // 1) * (10 ** -digs)
#^^^ This also works for rounding tau to a specified digit of percision. 
# However, it does not include the trailing zeroes required in zyBooks,
# thus leading to this answer vvv
print(f'The value of tau to {digs} digits is: {tau:.{digs}f}')
