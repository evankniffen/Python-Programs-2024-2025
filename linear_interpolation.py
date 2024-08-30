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
timeOne = 10
timeTwo = 55
positionOne = 2028
positionTwo = 23028 
slope = (positionTwo - positionOne) / (timeTwo - timeOne) 
circISS = 6745 * 2 * math.pi # using the circumference of our orbit to find our final position 

def linearFunction(x): 
    modDist = ((x - timeOne) * slope + positionOne) % circISS
    print("For t =",x,"minutes, the position p =",modDist,"kilometers")
    
print("Part 1:")    
linearFunction(25)
print("Part 2:")
linearFunction(300)