# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 3.17
# Date:         8 - 30 - 2024
#
from math import *
# converts units
num = float(input("Please enter the quantity to be converted: "))
print(f'{num:.2f} pounds force is equivalent to {num * 4.44822:.2f} newtons')
print(f'{num:.2f} meters is equivalent to {num * 3.28084:.2f} feet')
print(f'{num:.2f} atmospheres is equivalent to {num * 101.325:.2f} kilopascals')
print(f'{num:.2f} watts is equivalent to {num * 3.412141633:.2f} BTU per hour')
print(f'{num:.2f} liters per second is equivalent to {num * 15.85:.2f} US gallons per minute')
print(f'{num:.2f} degrees Celsius is equivalent to {num * 9 / 5 + 32:.2f} degrees Fahrenheit')