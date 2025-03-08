import numpy as np
from scipy.optimize import linprog

def main_scipy():
    c = np.array([-300, 250, -350, 400, -400, 350, -500, 550])
    A = np.array([
        [1,  -1,  1,   0,   0,   0,   0,   0],
        [ 1, -1,  1,  -1,   1,   0,   0,   0],
        [ 1, -1,  1,  -1,   1,  -1,   1,   0],
        [-1,  1, -1,   1,  -1,   1,  -1,   1],
        [ 1, -1,  1,  -1,   1,  -1,   1,  -1],

        [300, -250, 0,    0,    0,    0,    0,    0],
        [300, -250, 350,  -400,   0,    0,    0,    0],
        [300, -250, 350,  -400, 400,  -350,   0,    0],
        [300, -250, 350,  -400, 400,  -350, 500, -550],
    ])
    b = np.array([
        100,100,100,0,0,1000,1000,1000,1000
    ])
    result = linprog(-c, A_ub=A, b_ub=b)
    print(result)
    print()
    if result.success:
        print("Optimal objective value=", -result.fun)
        print("sell plan =", result.x)
        print("Final $$$ =", 1000 + (-result.fun))
    else:
        print("All bad no good", result.message)
if __name__=="__main__":
    main_scipy()
