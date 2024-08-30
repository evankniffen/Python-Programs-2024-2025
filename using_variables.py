# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 2.9
# Date:         8 - 26 - 2024
#
import math
# outputs the math statements. 
reynolds = (9*.875)/.0015
wave = 2*.028*math.sin(35*(math.pi/180))
barrels = 100/(math.pow(1+.8*2*10,1/.8))
velocity = 2028*math.log(11000/8300)
print("Reynolds number is",reynolds)
print("Wavelength is",wave,"nm")
print("Production rate is",barrels,"barrels/day")
print("Change of velocity is",velocity,"m/s")