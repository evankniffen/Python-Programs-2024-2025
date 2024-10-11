

x = 3
y = "A"
for i in range(10):
    x *= 2
    y += y
    if x > 6:
        break
print(f"{x}{y}")