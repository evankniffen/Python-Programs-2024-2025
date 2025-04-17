import numpy as np
import matplotlib.pyplot as plt
from scipy.integrate import odeint

L = 1.0
R = 2.0
C = 2.0 
def E(t):
    return 2 * np.heaviside(t - np.pi, 1)

def rlc_system(y, t):
    u, v = y
    du_dt = v
    dv_dt = E(t) - 2 * v - 0.5 * u
    return [du_dt, dv_dt]

y0_rlc = [2, 0]
t_rlc = np.linspace(0, 20, 1000)
sol_rlc = odeint(rlc_system, y0_rlc, t_rlc)
q = sol_rlc[:, 0] 
I = sol_rlc[:, 1] 

plt.figure(figsize=(12, 5))
plt.subplot(1, 2, 1)
plt.plot(t_rlc, q, label='q(t)', color='blue')
plt.xlabel('Time t (sec)')
plt.ylabel('Charge (C)')
plt.title('Charge on the Capacitor')
plt.legend()
plt.grid(True)
plt.subplot(1, 2, 2)
plt.plot(t_rlc, I, label="I(t) = q'(t)", color='red')
plt.xlabel('Time t (sec)')
plt.ylabel('Current (A)')
plt.title('Current in the Circuit')
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()
plt.figure(figsize=(6, 5))
plt.plot(q, I, 'm-')
plt.xlabel('Charge q(t) (C)')
plt.ylabel("Current I(t) (A)")
plt.title('Phase Portrait: Charge vs. Current')
plt.grid(True)
plt.show()

print(sol_rlc)

def spring_mass_system(y, t):
    u, v = y
    du_dt = v
    dv_dt = 2 * np.sin(t) - u
    return [du_dt, dv_dt]
y0_spring = [2, 0]
t_spring = np.linspace(0, 20, 1000)
sol_spring = odeint(spring_mass_system, y0_spring, t_spring)
x = sol_spring[:, 0]  
v = sol_spring[:, 1] 
plt.figure(figsize=(12, 5))

plt.subplot(1, 2, 1)
plt.plot(t_spring, x, label='x(t)', color='green')
plt.xlabel('Time t (sec)')
plt.ylabel('Displacement (m)')
plt.title('Displacement of the Mass')
plt.legend()
plt.grid(True)
plt.subplot(1, 2, 2)
plt.plot(t_spring, v, label="v(t) = x'(t)", color='orange')
plt.xlabel('Time t (sec)')
plt.ylabel('Velocity (m/s)')
plt.title('Velocity of the Mass')
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()
plt.figure(figsize=(6, 5))
plt.plot(x, v, 'c-')
plt.xlabel('Displacement x(t) (m)')
plt.ylabel("Velocity v(t) (m/s)")
plt.title('Phase Portrait: Displacement vs. Velocity')
plt.grid(True)
plt.show()

print(sol_spring)