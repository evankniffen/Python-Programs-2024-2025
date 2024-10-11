# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 7
# Date:         10 - 09 - 2024
#
count = 0
dict = {}

for num in range(10000):
    numStr = str(num)

    if numStr == '1111' or numStr == '2222' or numStr == '3333' or numStr == '4444' or \
       numStr == '5555' or numStr == '6666' or numStr == '7777' or numStr == '8888' or numStr == '9999':
        count +=1 
    else:
        while int(numStr) != 6174:
            if numStr in dict:
                count += dict[numStr]
                break

            numList = [int(x) for x in numStr]
            while len(numList) < 4:
                numList.insert(0, 0)

            numList.sort()
            lowNum = int("".join([str(x) for x in numList]))
            hiNum = int("".join([str(x) for x in numList[::-1]]))
            numStr = str(hiNum - lowNum)

            while len(numStr) < 4:
                numStr = '0' + numStr
            count += 1

print(f"Kaprekar's routine takes {count} total iterations for all four-digit numbers.")

