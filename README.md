# SMR Lab's Active Middleware Services (AMS) 

> designed for the Smart Manufactoring Research Lab @ WKU

---
## About

A smart manufacturing data platform for collecting, monitoring, and storing telemetry from distributed edge devices such as IMUs, cameras, and robot systems.

This project centers on a containerized data broker architecture that receives data from edge devices, stores it in a database, and provides a live dashboard for monitoring sessions, backups, and device activity.

---
## Related Work

This is just one part of the system, see:

[imu edge node](https://github.com/cylissama/wku-smr-lab-imu-edge-node)

and

[camera edge node](https://github.com/UmarKhattab09/camera_sensor_fusion)

for our other components

---

## Overview

The system is designed to support:

- real-time telemetry ingestion
- session-based data collection
- live dashboard monitoring
- database backup and restore workflows
- edge-device communication through MQTT and TCP
- modular deployment with Docker

At a high level, this AMS includes:

- **MQTT broker** for sensor-style device messaging
- **FastAPI server** for ingestion, session control, and websocket updates
- **TCP server** for robot data ingestion
- **Web dashboard** built with React + Vite
- **Database integration** for sessioned telemetry storage
- **NTP service** for time synchronization support
