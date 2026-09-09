# Smart Manufactoring Research Lab @ WKU

A smart manufacturing data platform for collecting, monitoring, and storing telemetry from distributed edge devices such as IMUs, cameras, and robot systems.

This project centers on a containerized data broker architecture that receives data from edge devices, stores it in a database, and provides a live dashboard for monitoring sessions, backups, and device activity.

## Overview

The system is designed to support:

- real-time telemetry ingestion
- session-based data collection
- live dashboard monitoring
- database backup and restore workflows
- edge-device communication through MQTT and TCP
- modular deployment with Docker

At a high level, the system includes:

- **MQTT broker** for sensor-style device messaging
- **FastAPI server** for ingestion, session control, and websocket updates
- **TCP server** for robot data ingestion
- **Web dashboard** built with React + Vite
- **Database integration** for sessioned telemetry storage
- **NTP service** for time synchronization support

## Repository Structure

```text
CS560-Smart-Manufacturing-Data/
├── project/
│   ├── db/                # Database logic and schema-related code
│   ├── fast_server/       # FastAPI backend and websocket/message handling
│   ├── mqtt_conf/         # MQTT broker configuration
│   ├── tcp_server/        # TCP server for robot telemetry
│   ├── tests/             # Test scripts and local utilities
│   ├── web/               # React/Vite dashboard frontend
│   ├── docker-compose.yml
│   ├── dockerfile
│   └── requirements.txt
└── README.md
