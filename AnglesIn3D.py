# Python Code for finding all angles of a triangle 
import math 
 
# function for finding the angle 
def angle_triangle(x1, x2, x3, y1, y2, y3, z1, z2, z3): 
 
    num = (x2-x1)*(x3-x1)+(y2-y1)*(y3-y1)+(z2-z1)*(z3-z1) 
 
    den = math.sqrt((x2-x1)**2+(y2-y1)**2+(z2-z1)**2)*\
                math.sqrt((x3-x1)**2+(y3-y1)**2+(z3-z1)**2) 
 
    angle = math.degrees(math.acos(num / den)) 
 
    return round(angle, 3) 
 
# driver code     
x1 = 1
y1 = 0
z1 = -1
x2 = 5
y2 = -5
z2 = 0
x3 = 1
y3 = 4
z3 = 2
angle_A = angle_triangle(x1, x2, x3, y1, y2, y3, z1, z2, z3) 
angle_B = angle_triangle(x2, x3, x1, y2, y3, y1, z2, z3, z1) 
angle_C = angle_triangle(x3, x2, x1, y3, y2, y1, z3, z2, z1) 
print("Angles are :") 
print("angle A = ", angle_A, "degree") 
print("angle B = ", angle_B, "degree") 
print("angle C = ", angle_C, "degree") 