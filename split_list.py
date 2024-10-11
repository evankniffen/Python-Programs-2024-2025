# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 7
# Date:         10 - 09 - 2024
#
nums = input("Enter numbers: ")
numsList = [int(x) for x in nums.split()]

sum1 = 0
sum2 = 0
canSplit = False

for split in range(1, len(numsList)):
    sum1 = 0
    sum2 = 0
    
    for i in range(split):
        sum1 += numsList[i]
        
    for j in range(split, len(numsList)):
        sum2 += numsList[j]
        
    if sum1 == sum2:
        #Splices th elists to ensure correct output
        print(f"Left: {numsList[:split]}")
        print(f"Right: {numsList[split:]}")
        print(f"Both sum to {sum1}")
        canSplit = True
        break

if not canSplit:
    print("Cannot split evenly")

