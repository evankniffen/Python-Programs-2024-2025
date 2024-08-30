# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 1.13
# Date:         8 - 20 - 2024
#
import math 

print("This shows the evaluation of (1-cos(x))/x^2 evaluated close to x=0")
print("My guess is .5")

# now we start at x=1 and multiply by .1 with each iteration

print((1-math.cos(1))/math.pow(1,2))
print((1-math.cos(.1))/math.pow(.1,2))
print((1-math.cos(.01))/math.pow(.01,2))
print((1-math.cos(.001))/math.pow(.001,2))
print((1-math.cos(.0001))/math.pow(.0001,2))
print((1-math.cos(.00001))/math.pow(.00001,2))
print((1-math.cos(.000001))/math.pow(.000001,2))
print((1-math.cos(.0000001))/math.pow(.0000001,2))
print()
print("Nailed it")