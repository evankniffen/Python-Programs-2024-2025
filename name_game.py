# By submitting this assignment, I agree to the following:
#   "Aggies do not lie, cheat, or steal, or tolerate those who do."
#   "I have not given or received any unauthorized aid on this assignment."
#
# Name:         Evan Kniffen
# Section:      507
# Assignment:   Lab 7
# Date:         10 - 09 - 2024
#
name = input("What is your name? ")
nameLower = name.lower()
vowels = "aeiou"
namePlusY = ""

if nameLower[0] in vowels:
    namePlusY = nameLower
else:
    foundVowel = False
    for i in range(len(nameLower)):
        # tries to find a vowel
        if nameLower[i] in vowels:
            namePlusY = nameLower[i:]
            foundVowel = True
            break
    if not foundVowel:
        namePlusY = nameLower

bo = name + ", " + name + ", Bo-B" + namePlusY
banana = "Banana-Fana Fo-F" + namePlusY
meMiMo = "Me Mi Mo-M" + namePlusY
final = name + "!"

print(bo)
print(banana)
print(meMiMo)
print(final)
