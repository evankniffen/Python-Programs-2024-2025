# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 6.1
# Date:         9 - 25 - 2024
#

sideLen = float(input("Enter the side length in meters: "))
layers = int(input("Enter the number of layers: "))
# summing with a for loop
sum = 0
for i in range(layers):
    sum += (sideLen ** 2) * (6 * i + 5)

print(f"You need {sum:.2f} m^2 of gold foil to cover the pyramid")