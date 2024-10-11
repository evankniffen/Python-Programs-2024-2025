# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 6.17
# Date:         9 - 30 - 2024
#

num1 = int(input("Enter an integer: "))
num2 = int(input("Enter another integer: "))
# summing with an equation
sum = 0
for i in range(num1,num2 + 1):
    sum += i
print(f"The sum of all integers from {num1} to {num2} is {sum}")
