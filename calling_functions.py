# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 3.2
# Date:         8 - 28 - 2024
#
from math import *

def printresult(shape, side, area):
    '''Print the result of the calculation'''
    print(f'A {shape} with side {side:.2f} has area {area:.3f}')

def regPolyArea(num, len):
        if num == 4:
            return len ** 2
        # python evaluates tan(pi/4) as .99999 instead of 1 :(
        return ((len ** 2 * num) / (4 * tan(pi / num)))

sideLength = float(input("Please enter the side length: "))

valList = [[3,4,5,6,12],["triangle","square","pentagon","hexagon","dodecagon"]]

# for i in range(len(valList[0])): 
#       printresult(valList[1][i],sideLength,regPolyArea(valList[0][i],sideLength))
# it wants me to do printresult() for every shape. bruh.

printresult(valList[1][0],sideLength,regPolyArea(valList[0][0],sideLength))
printresult(valList[1][1],sideLength,regPolyArea(valList[0][1],sideLength))
printresult(valList[1][2],sideLength,regPolyArea(valList[0][2],sideLength))
printresult(valList[1][3],sideLength,regPolyArea(valList[0][3],sideLength))
printresult(valList[1][4],sideLength,regPolyArea(valList[0][4],sideLength))