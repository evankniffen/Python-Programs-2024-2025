# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 4.18
# Date:         9 - 05 - 2024
#

# finds the largest number
from math import *

num1 = float(input("Enter number 1: "))
num2 = float(input("Enter number 2: "))
num3 = float(input("Enter number 3: "))

numList = [num1,num2,num3]

max = -inf

for i in range(len(numList)) : 
    if numList[i] > max :
        max = numList[i]

print("The largest number is",max)