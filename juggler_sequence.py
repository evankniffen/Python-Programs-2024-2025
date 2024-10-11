# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 6.19
# Date:         9 - 30 - 2024
#

num = int(input("Enter a positive integer: "))
print(f"The Juggler sequence starting at {num} is:")
numList = str(num) + ", " if num != 1 else str(num)
count = 0
# evaluates the juggler sequence based on the parity of the number
while num > 1:
    if num % 2 == 0:
        num = num ** (1 / 2) // 1
    else:
        num = num ** (3 / 2) // 1
    if num != 1:
        numList += f"{int(num)}, "
    else:
        numList += "1"
    count += 1
print(numList)
print(f"It took {count} iterations to reach 1")