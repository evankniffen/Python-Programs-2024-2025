# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 4.16
# Date:         9 - 04 - 2024
#
from math import *

varList = [input("Please enter the coefficient A: "),input("Please enter the coefficient B: "),input("Please enter the coefficient C: ")]
strList = ["x^2 ","x ",""]
#test if we print them, if not, then their coefficient is 0.
printList = [True,True,True]

for i in range(3):
    if varList[i] == "0" :
         printList[i] = False
    else :
        if abs(int(varList[i])) == 1 :
                if int(varList[i]) < 0:
                    varList[i] = "- " + strList[i]
                else :
                    varList[i] = "+ " + strList[i] 
                if i == 2 :
                    varList[i] += "1"
        else :
            if int(varList[i]) < 0 :
                varList[i] = "- " + str(abs(int(varList[i]))) + strList[i]
            else :
                varList[i] = "+ " + varList[i] + strList[i]
        if i == 0 and varList[0][0] == "+":
            varList[0] = varList[0][2:]

print(f"The quadratic equation is {varList[0] if printList[0] == True else ""}{varList[1] if printList[1] == True else ""}{varList[2] if printList[2] == True else ""} = 0")