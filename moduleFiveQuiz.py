num = int(input("Enter a four digit number:"))
dig1 = num // 1000
dig2 = (num // 100) % 10
dig3 = (num // 10) % 10
dig4 = num % 10
digSum = dig1 + dig2 + dig3 + dig4
print(dig1," ",dig2," ",dig3," ",dig4)
if (digSum ** 3 // 1 == num):
    print("true")
else:
    print("false")