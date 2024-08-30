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
# allowing for user inputs
print("This program calculates the Reynolds number given velocity, length, and viscosity")
velocityR = float(input("Please enter the velocity (m/s): "))
dimensionL = float(input("Please enter the length (m): "))
viscosity = float(input("Please enter the viscosity (m^2/s): "))
print(f"Reynolds number is {((velocityR * dimensionL) / viscosity):.0f}\n")
print("This program calculates the wavelength given distance and angle")
nanom = float(input("Please enter the distance (nm): "))
theta = float(input("Please enter the angle (degrees): "))
print(f"Wavelength is {2 * nanom * sin(theta * (pi / 180)):.4f} nm\n")
print("This program calculates the production rate given time, initial rate, and decline rate")
days = float(input("Please enter the time (days): "))
prodrate = float(input("Please enter the initial rate (barrels/day): "))
decrate = float(input("Please enter the decline rate (1/day): "))
hyperC = .8
print(f"Production rate is {prodrate / (pow(1 + decrate * days * hyperC,1 / hyperC)):.2f} barrels/day\n")
print("This program calculates the change of velocity given initial mass, final mass, and exhaust velocity")
initialM = float(input("Please enter the initial mass (kg): "))
finalM = float(input("Please enter the final mass (kg): "))
velocityE = float(input("Please enter the exhaust velocity (m/s): "))
print(f"Change of velocity is {velocityE * log(initialM / finalM):.1f} m/s\n")