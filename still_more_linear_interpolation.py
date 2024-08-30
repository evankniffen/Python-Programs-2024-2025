# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 3.0
# Date:         8 - 28 - 2024
#
import math
# allowing for user inputs
timeOne = float(input("Enter time 1: "))
x1 = float(input("Enter the x position of the object at time 1: "))
y1 = float(input("Enter the y position of the object at time 1: "))
z1 = float(input("Enter the z position of the object at time 1: "))
timeTwo = float(input("Enter time 2: "))
x2 = float(input("Enter the x position of the object at time 2: "))
y2 = float(input("Enter the y position of the object at time 2: "))
z2 = float(input("Enter the z position of the object at time 2: "))
slopeX = (x2 - x1) / (timeTwo - timeOne) 
slopeY = (y2 - y1) / (timeTwo - timeOne) 
slopeZ = (z2 - z1) / (timeTwo - timeOne) 
space = (timeOne - timeTwo) / 4
timeList = [timeOne,timeOne - space,timeOne - 2 * space,timeOne - 3 * space,timeTwo]
print()
for i in range(5):
    xVal = ((timeList[i] - timeOne) * slopeX + x1)
    yVal = ((timeList[i] - timeOne) * slopeY + y1)
    zVal = ((timeList[i] - timeOne) * slopeZ + z1)
    print(f'At time {timeList[i]:.2f} seconds the object is at ({xVal:.3f}, {yVal:.3f}, {zVal:.3f})')
