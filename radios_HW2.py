import numpy as np
from scipy.optimize import linprog

def main_scipy():
    c = np.array([750,650,550,450,-700,-500,-300,-100,0,0,0,0])
    A = np.array([ [1,0,0,0,0,0,0,0,1,0,0,0],
                   [0,1,0,0,-1,0,0,0,0,1,0,0],
                   [0,0,1,0,-1,-1,0,0,0,0,1,0],
                   [0,0,0,1,-1,-1,-1,0,0,0,0,1],

                   [-1,-1,-1,-1,0,0,0,0,0,0,0,0],

                   [0,0,0,0,1,0,0,0,-3,0,0,0],
                   [0,0,0,0,0,1,0,0,0,-3,0,0],
                   [0,0,0,0,0,0,1,0,0,0,-3,0],
                   [0,0,0,0,0,0,0,1,0,0,0,-3],
    ])
    b = np.array([
        40,40,40,40,-400,0,0,0,0
    ])
    result = linprog(-c, A_ub=A, b_ub=b)
    print(result)
    print()
    if result.success:
        print("Optimal objective value=", -result.fun)
        print("plan =", result.x)
        print("Final $$$ =", -160*200 + (-result.fun))
    else:
        print("All bad no good", result.message)
if __name__=="__main__":
    main_scipy()
