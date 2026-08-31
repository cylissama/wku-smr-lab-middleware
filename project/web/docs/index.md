---
# https://vitepress.dev/reference/default-theme-home-page
layout: home

hero:
  name: "SMR Documentation"
  text: "Smart Manufacturing Data Broker Middleware"
  tagline: Ingestion, storage, and dashboard docs for the WKU Smart Manufacturing Research Lab's edge-device data platform.
  actions:
    - theme: brand
      text: What is this project?
      link: /overview/what-is-this
    - theme: alt
      text: How it's structured
      link: /overview/structure
    - theme: alt
      text: GitHub
      link: https://github.com/cylissama/wku-smr-lab-middleware

features:
  - title: Overview
    details: What the platform does and how the repository is organized.
    link: /overview/what-is-this
  - title: Hardware
    details: IMU nodes, camera nodes, the robot, and the machines that run the middleware.
    link: /hardware/
  - title: Data
    details: How telemetry is stored, queried, backed up — and the tables behind it.
    link: /data/database-uses
  - title: Docker
    details: The Compose stack, the IMU Swarm cluster, and what runs automatically.
    link: /docker/compose
  - title: Network
    details: Hosts, IP addresses, and ports across the lab network.
    link: /network/topology
---
