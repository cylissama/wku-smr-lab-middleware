currently this project is configured to received data on the dashboard, and save that data always. Whenever an edge device or the robot sends data, the dashboard takes in the data.

We want to change this system so that we only listen and store the data when we want to, and all other data is not captured. 

I plan to start listening when we start a session, so data is only stored when we start a session. We could also have a seperate, non-session listen mode that will display the data sent to the AMS, but not store it, this could be for testing purposes. 

Second

We also want the capability of to only test certain parts of the system at once. Say we only want to run the imu edge devices, or only want to run the camera edge devices, or even we just want to run a single device we have deployed. There should be a checkbox where we can view all the devices and choose if we would like to test all devices or just a few or just one category. 

Create a plan and then present to me
