# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 4.15
# Date:         9 - 04 - 2024
#
from math import *
# cost analysis
paid = float(input("How much did you pay? "))
cost = float(input("How much did it cost? "))
change = paid - cost
print(f'You received ${change:.2f} in change. That is...')
quarters = int(change // .25)
dimes = int((change - .25 * quarters) // .1)
nickels = int((change - .25 * quarters - .1 * dimes) // .05)
pennies = int((((change - .25 * quarters - .1 * dimes - .05 * nickels) * 100) * 10 + .5) / 10)
# sometimes 1 evaluates to .9999999, thus the need to round
(print(quarters,"quarters") if quarters > 1 else print(quarters,"quarter")) if quarters > 0 else None
(print(dimes,"dimes") if dimes > 1 else print(dimes,"dime")) if dimes > 0 else None
(print(nickels,"nickels") if nickels > 1 else print(nickels,"nickel")) if nickels > 0 else None
(print(pennies,"pennies") if pennies > 1 else print(pennies,"penny")) if pennies > 0 else None
