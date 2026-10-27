## Goal
Currently out .env and swarm.yml control what devices we have and what parameters we give each of those devices and our system. We want to make a change to how we add, update, and manipulate these variables.

The idea is to have a parameter dialoge box on the dashboard that will allow the user to update these parameters on the fly. There will be a container to the right of the screen on which the dashbaord is displayed and will have boxes for each parameter with its current value. We will be able to update these on a per run basis, and we should be blocked from changing them while a session is running. 

What would be the safest and most efficient way to accomplish this type of system upgrade? Do we store the parameters and enviornment varaiables in the same location? Do some reserach and create a plan to accomplish this.

The right area of the screen on the dashboard is where this box of parameters should live, and operate similar to how the left hand side devices icons display. 

An example of a parameter we could change on seperate session runs would be the IMU_SAMPLE_HZ value on the .env file. Another important param we would change could be IMU_PLC_TRIGGER
