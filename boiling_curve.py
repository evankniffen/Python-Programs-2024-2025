# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 5.1
# Date:         9 - 25 - 2024
#
from math import *

x = float(input("Enter the excess temperature: "))
# evaluate the points
ax = 1.3
ay = 1000
bx = 5
by = 7000
cx = 30
cy = 1.5 * 10 ** 6
dx = 120
dy = 2.5 * 10 ** 4
ex = 1200
ey = 1.5 * 10 ** 6
# calculate the slope logarithmically
abslope = log(by / ay) / log(bx / ax)
bcslope = log(cy / by) / log(cx / bx)
cdslope = log(dy / cy) / log(dx / cx)
deslope = log(ey / dy) / log(ex / dx)
# conditional staements to determine which points it is in between
if x < ax or x > ex:
    # test if out of domain
    print("Surface heat flux is not available")
elif x >= ax and x < bx:\
    #test if in AB
    temp = ay * (x / ax) ** abslope 
    print("The surface heat flux is approximately",int((temp + .5) // 1),"W/m^2") # uses the .5 // 1 to round to nearest integer
elif x >= bx and x < cx:
    #test if in BC
    temp = by * (x / bx) ** bcslope
    print("The surface heat flux is approximately",int((temp + .5) // 1),"W/m^2")
elif x >= cx and x < dx:
    #test if in CD
    temp = cy * (x / cx) ** cdslope
    print("The surface heat flux is approximately",int((temp + .5) // 1),"W/m^2")
elif x >= dx and x <= ex:
    #test if in DE
    temp = dy * (x / dx) ** deslope
    print("The surface heat flux is approximately",int((temp + .5) // 1),"W/m^2")

# will print the error message or a calculated response based on conditionals