# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 2.8
# Date:         8 - 21 - 2024
#
import math
# time is our x-var, position is our y-var
timeOne = 12
timeTwo = 85
x1 = 8
x2 = -5
y1 = 6
y2 = 30
z1 = 7
z2 = 9
slopeX = (x2 - x1) / (timeTwo - timeOne) 
slopeY = (y2 - y1) / (timeTwo - timeOne) 
slopeZ = (z2 - z1) / (timeTwo - timeOne) 
timeList = [30,37.5,45,52.5,60]

for i in range(5):
    xVal = ((timeList[i] - timeOne) * slopeX + x1)
    yVal = ((timeList[i] - timeOne) * slopeY + y1)
    zVal = ((timeList[i] - timeOne) * slopeZ + z1)
    print("At time",float(timeList[i]),"seconds:")
    print(f'x{i+1}  = {xVal} m')
    print(f'y{i+1}  = {yVal} m')
    print(f'z{i+1}  = {zVal} m')
    if i != 4 :
        print("-----------------------")

