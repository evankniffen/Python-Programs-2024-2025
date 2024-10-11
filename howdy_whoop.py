# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 6.16
# Date:         9 - 30 - 2024
#

num1 = int(input("Enter an integer: "))
num2 = int(input("Enter another integer: "))

howdywhoop = ""
# for loop defining the parameters
for i in range(1,101):
    if (i % num1 == 0):
        howdywhoop += "Howdy "
    if (i % num2 == 0):
        howdywhoop += "Whoop "
    if (i % num1 != 0 and i % num2 != 0):
        howdywhoop += str(i)
    print(howdywhoop)
    howdywhoop = ""
    