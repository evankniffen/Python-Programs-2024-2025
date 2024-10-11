# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 7
# Date:         10 - 09 - 2024
#
num = input("Enter a four-digit integer: ")
count = 0
steps = [num]
# Handles the case s.t. all digits are the same.
if int(num) == 1111 or int(num) == 2222 or int(num) == 3333 or int(num) == 4444 or int(num) == 5555 or int(num) == 6666 or int(num) == 7777 or int(num) == 8888 or int(num) == 9999:
    print(num,"> 0")
    print(num," reaches 0 via Kaprekar's routine in 1 iterations")
else:
    while int(num) != 6174:
        numList = list(num)
        while len(numList) < 4:
            numList.insert(0, '0')
        numList.sort()
        hiNum = int("".join(numList))
        lowNum = int("".join(numList[::-1]))
        num = str(lowNum - hiNum)
        steps.append(num)
        count += 1

    print(" > ".join(steps))
    print(f"{steps[0]} reaches 6174 via Kaprekar's routine in {count} iterations")

