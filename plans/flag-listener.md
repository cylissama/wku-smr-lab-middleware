The current system we want to implement is the following:

The PLC currently is sending a flag when the robot is done moving. Theis PLC tag is broadcast over the network on a specific IP. We need to listen for this flag on the AMS, and once we read it as a 1, we want to stop the current session.
The session stop prodecure should be the exact same as the current process where we press the stop button on the dashboard, but iinstead of pressing the button, we automate it based off the read PLC tag.


The logic for reading the PLC tag is already implemented inside the IMU edge nodes here: https://github.com/cylissama/wku-smr-lab-imu-edge-node/tree/plc_update


so analyze that then determine how we should do it on the AMS.


Plan it out, where, how and in what way should we implement this in the AMS
