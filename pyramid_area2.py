# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 6.2
# Date:         9 - 25 - 2024
#

sideLen = float(input("Enter the side length in meters: "))
layers = int(input("Enter the number of layers: "))
# summing with an equation
sum = (sideLen ** 2) * (3 * layers ** 2 + 2 * layers)

print(f"You need {sum:.2f} m^2 of gold foil to cover the pyramid")
