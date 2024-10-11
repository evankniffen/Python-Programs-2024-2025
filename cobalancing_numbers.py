# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 6.20
# Date:         9 - 30 - 2024
#

num = int(input("Enter a value for n: "))
sum1 = 0
sum2 = 0
for i in range(num + 1):
    sum1 += i
n = num + 1
while sum2 < sum1:
    sum2 += n
    n += 1
# tests whether the number was calculated to be a co-balancing number
if sum2 != sum1:
    print(num,"is not a co-balancing number")
else:
    print(f"{num} is a co-balancing number with r={n-num-1}")