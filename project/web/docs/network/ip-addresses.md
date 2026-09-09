# IP Address Table

## Where the AMS lives
192.168.2.100


::: danger
This page contains plaintext credentials for lab network equipment. It is committed to the repository and served by the docs site — treat it as sensitive. Only reference/update it internally.
:::

## 192.168.1.XX

| Device | IP Address | MAC Address | Username | Password | Notes |
| --- | --- | --- | --- | --- | --- |
| UXG-FIBER | 192.168.1.1 | | | | |
| CONTROLLER | 192.168.1.10 | | | password | Port `:8443`; also `student_viewer` / `student_password` |
| USW-XG PRO 24 | DHCP | | | | |
| FANUC1 | 192.168.1.100 | 00:e0:e4:35:94:4d | | | |
| FANUC2 | 192.168.1.101 | 00:e0:e4:35:94:4e | | | Not connected |
| ROBOT PI | 192.168.1.102 | | | | Not developed |
| L32E | 192.168.1.103 | 00:00:bc:40:11:a4 | | | |
| NAS DRIVE 10G | 192.168.1.104 | 90:09:D0:A0:B9:6B | wkuadmin | Password1906 | Share: `WKU_IIOT` |
| — | 192.168.1.105 | | | | |
| RPI_IMU_J1 | 192.168.1.106 | 2C:CF:67:ED:E6:DA | admin | password | |
| RPI_IMU_J2 | 192.168.1.107 | 2C:CF:67:ED:72:B2 | admin | password | |
| RPI_IMU_J3 | 192.168.1.108 | 2C:CF:67:ED:E3:97 | admin | password | |
| RPI_IMU_J4 | 192.168.1.109 | 2C:CF:67:ED:E4:0B | admin | password | |
| RPI_IMU_J5 | 192.168.1.110 | 2C:CF:67:BE:B1:4F | admin | password | |
| RPI_IMU_J6 | 192.168.1.111 | | | | Needs to be built and connected |
| RPI_IMU_GT | 192.168.1.112 | | | | Needs to be built and connected |
| CAMERAFRONT | 192.168.1.113 | 2C:CF:67:4F:7F:BC | admin | admin | |
| CAMERAPI2 | 192.168.1.114 | 88:a2:9e:02:e2:93 | admin | admin | |
| CameraPi3 | 192.168.1.115 | | admin | password | Needs to be built and connected; secondary IP `192.168.4.42` |
| CameraPi4 | 192.168.1.116 | | | | Needs to be built and connected |
| CameraPi5 | 192.168.1.117 | | | | Needs to be built and connected |
| — | 192.168.1.118 | | | | |
| Alien Ware | 192.168.1.119 | | user | password | Needs to be moved and set up |
| — | 192.168.1.120–124 | | | | |

## 192.168.2.XX

USW PRO 24

| Device | IP Address | MAC Address | Username | Password | Notes |
| --- | --- | --- | --- | --- | --- |
| data-team mini s | 192.168.2.100 | E8:FF:1E:D9:58:B4 | data-team (linux) | 1234 | `ssh data-team@192.168.2.100` |
| ntp_MINI_s | 192.168.2.101 | E8:FF:1E:D9:58:93 | ntp | password | |
| Rack Pi | 192.168.2.31 | B8:27:EB:47:73:C3 | admin | password | |
| dell | DHCP | B0:4F:13:0A:1D:EE | | | |
| dell | DHCP | E4:B9:7A:F5:17:2C | | | |
| Middleware Dashboard | 192.168.2.100:80 | | data-team (linux) | 1234 | Need to test |
| Postgres Database | 192.168.2.111:5000 | | db_user | 1234 | See `192.168.1.111:5433`; need to test |
| pgAdmin GUI | 192.168.1.104:8080 | | admin@wku.edu | 1234 | Need to test |
| AXIS Camera | 192.168.2.36 | 00:40:8C:7F:33:80 | root | password | |

## 192.168.3.XX

USW PRO 24

| Device | IP Address | MAC Address | Username | Password | Notes |
| --- | --- | --- | --- | --- | --- |
| — | 192.168.3.100 | | | | |
| — | 192.168.3.101 | | | | |
| Keyence-Cam1 | 192.168.3.102 | 00:01:FC:02:19:3A | | | |
| — | 192.168.3.103 | | | | |
| RIO1 | 192.168.3.104 | 00:A0:3D:05:EC:D0 | | | |
| RIO2 | 192.168.3.105 | 00:A0:3D:05:EE:42 | | | |
| Mitsubishi-Steve* | 192.168.3.106 | | | | |
| PLC2-L16ER-B1BB | 192.168.3.107 | F4:54:33:A6:CD:D1 | | | |
| Keyence-Cam2 | 192.168.3.108 | 00:01:FC:00:B8:BE | | | |
| HMI-PanelView | 192.168.3.109 | 34:C0:F9:FF:13:F2 | | | |
| PLC3-L16ER-B1BB | 192.168.3.110 | BC:F4:99:1A:79:1E | | | |
| — | 192.168.3.111 | | | | |
| — | 192.168.3.112 | | | | |

## 192.168.4.XX

USW PRO 24

| Device | IP Address | MAC Address | Username | Password | Notes |
| --- | --- | --- | --- | --- | --- |
| AP | | 74:83:C2:BC:60:C7 | ubnt | password | SSID `Sandbox_AP`, password `password` |
| DisplayPi | 192.168.4.4 | B8:27:EB:B2:06:DC | admin | password | |
| AlienWare | DHCP | CC:96:E5:20:91:DB | | | |
| NAS_Backup | 192.168.4.236 | 90:09:D0:70:9D:23 | mcbuckle | NASpassword_207 | |
| Ubuntu Dell Computer (207) -2 | DHCP | | ubuntu | Password | Share/user group `IIoT` |
| WINDOWS PC | DHCP | B0:4F:13:12:11:8F | | | |
| DELL LAPTOP? | DHCP | B4:E9:B8:F7:A6:06 | | | |
| WINDOWS PC | DHCP | 50:9A:4C:52:2F:89 | | | |
| WINDOWS PC | DHCP | B0:4F:13:0B:FC:75 | | | |
| UBUNTU IMAGE | DHCP | B4:E9:B8:F7:A6:5E | username | password | |
| WINDOWS PC | DHCP | 68:1C:A2:12:22:0C | | | |
| WINDOWS PC | DHCP | B0:4F:13:0D:A8:9E | | | |
| WINDOWS PC | DHCP | B0:4F:13:0C:83:BF | | | |
| WINDOWS PC | DHCP | B0:4F:13:11:FF:47 | | | |
| WINDOWS PC | DHCP | B0:4F:13:0C:11:F9 | | | |
| WINDOWS PC | DHCP | B0:4F:13:11:03:CD | | | |
| APPLE MACBOOK | DHCP | A4:FC:14:2C:C4:93 | | | |
| WINDOWS PC | DHCP | B0:4F:13:12:04:06 | | | |

> Note from source sheet: "NEED TO VERIFY ALL — I think there are more Ubuntu computers there so we need usernames and password."

## 192.168.5.XX

USW PRO 16

| Device | IP Address | MAC Address | Username | Password | Notes |
| --- | --- | --- | --- | --- | --- |
| Sandbox AP | DHCP | | Sandbox_AP | password | |
| Synology NAS | 192.168.5.254 | | WKUIIoT | Password1! | Also `student` / `Hilltoppers123` |

**Flex Table 1**

| Device | IP Address | MAC Address | Username | Password |
| --- | --- | --- | --- | --- |
| ML1100-PLC1 | 192.168.5.11 | 00:0F:73:00:C4:F5 | | |
| HMIPi1 | 192.168.5.12 | 88:A2:9E:8D:39:72 | admin | password |
| RPiSH1 | 192.168.5.13 | 2C:CF:67:96:F3:31 | admin | password |

**Flex Table 2**

| Device | IP Address | MAC Address | Username | Password |
| --- | --- | --- | --- | --- |
| ML1100-PLC2 | 192.168.5.21 | 00:0F:73:00:C4:EF | | |
| HMIPi2 | 192.168.5.22 | 88:A2:9E:8D:8A:9F | admin | password |
| RPiSH2 | 192.168.5.23 | 2C:CF:67:96:FD:96 | admin | password |

**Flex Table 3**

| Device | IP Address | MAC Address | Username | Password |
| --- | --- | --- | --- | --- |
| ML1100-PLC3 | 192.168.5.31 | 00:0F:73:02:C6:22 | | |
| HMIPi3 | 192.168.5.32 | 88:A2:9E:8D:1B:B9 | admin | password |
| RPiSH3 | 192.168.5.33 | 2C:CF:67:96:FE:8A | admin | password |

**Flex Table 4**

| Device | IP Address | MAC Address | Username | Password |
| --- | --- | --- | --- | --- |
| ML1100-PLC4 | 192.168.5.41 | 00:0F:73:00:2F:46 | | |
| HMIPi4 | 192.168.5.42 | 88:A2:9E:8D:9E:E6 | admin | password |
| RPiSH4 | 192.168.5.43 | 2C:CF:67:96:FF:8F | admin | password |

**Flex Table 5**

| Device | IP Address | MAC Address | Username | Password |
| --- | --- | --- | --- | --- |
| ML1100-PLC5 | 192.168.5.51 | 00:0F:73:00:30:13 | | |
| HMIPi5 | 192.168.5.52 | 88:A2:9E:8D:1B:C9 | admin | password |
| RPiSH5 | 192.168.5.53 | 2C:CF:67:96:FE:29 | admin | password |

**Flex Table 6**

| Device | IP Address | MAC Address | Username | Password |
| --- | --- | --- | --- | --- |
| ML1100-PLC6 | 192.168.5.61 | 00:0F:73:00:30:11 | | |
| HMIPi6 | 192.168.5.62 | 88:A2:9E:8D:19:E6 | admin | password |
| RPiSH6 | 192.168.5.63 | 2C:CF:67:96:FD:8A | admin | password |

**Flex Table 7**

| Device | IP Address | MAC Address | Username | Password |
| --- | --- | --- | --- | --- |
| ML1100-PLC7 | 192.168.5.71 | 00:0F:73:01:3B:EF | | |
| HMIPi7 | 192.168.5.72 | 88:A2:9E:8D:8C:B2 | admin | password |
| RPiSH7 | 192.168.5.73 | 2C:CF:67:96:FF:8F | admin | password |

**Flex Table 8**

| Device | IP Address | MAC Address | Username | Password |
| --- | --- | --- | --- | --- |
| ML1100-PLC8 | 192.168.5.81 | 00:0F:73:00:2F:45 | | |
| HMIPi8 | 192.168.5.82 | 88:A2:9E:8D:43:D7 | admin | password |
| RPiSH8 | 192.168.5.83 | 2C:CF:67:96:FE:E1 | admin | password |

**Flex Table 9**

| Device | IP Address | MAC Address | Username | Password |
| --- | --- | --- | --- | --- |
| ML1100-PLC9 | 192.168.5.91 | 00:0F:73:00:30:14 | | |
| HMIPi9 | 192.168.5.92 | 88:A2:9E:8D:93:78 | admin | password |
| RPiSH9 | 192.168.5.93 | 2C:CF:67:96:FE:6B | admin | password |

**Flex Table 10**

| Device | IP Address | MAC Address | Username | Password |
| --- | --- | --- | --- | --- |
| ML1100-PLC10 | 192.168.5.101 | 00:0F:73:00:2F:45 | | |
| HMIPi10 | 192.168.5.102 | 88:A2:9E:8D:97:C2 | admin | password |
| RPiSH10 | 192.168.5.103 | 2C:CF:67:C3:51:A7 | admin | password |

## 192.168.6.XX

Windows PCs (DHCP, no static IP):

| MAC Address |
| --- |
| B0:7B:25:2C:44:90 |
| B0:7B:25:2C:36:E2 |
| B0:7B:25:2C:45:2B |
| B0:7B:25:2C:3F:C5 |
| B0:7B:25:2C:46:14 |
| B0:7B:25:2C:45:4A |
| B0:7B:25:2C:42:B7 |
| B0:7B:25:2C:3F:0D |
| B0:7B:25:2C:46:73 |
| B0:7B:25:2C:46:22 |
| B0:7B:25:2C:37:46 |
| B0:7B:25:2C:46:99 |
| B0:7B:25:2C:46:1C |
| B0:7B:25:2C:37:85 |
| B0:7B:25:2C:35:63 |
| B0:7B:25:2C:46:1B |
| B0:7B:25:2C:38:4E |
| B0:7B:25:2C:46:94 |
| B0:7B:25:2C:46:23 |
| B0:7B:25:2C:46:4C |
| B0:7B:25:2C:36:F0 |

PLCs (static IPs):

| Device | IP Address | MAC Address |
| --- | --- | --- |
| L16ER-B1BB | 192.168.6.30 | F4:54:33:A5:CD:7F |
| L18ER-B1BB | 192.168.6.31 | F4:54:33:A8:38:C9 |
| L16ER-B1BB | 192.168.6.32 | F4:54:33:A6:CD:D8 |
| L16ER-B1BB | 192.168.6.33 | F4:54:33:A6:CD:52 |
| L16ER-B1BB | 192.168.6.34 | F4:54:33:A6:CD:AC |
| L16ER-B1BB | 192.168.6.35 | F4:54:33:A6:D4:AA |
| L16ER-B1BB | 192.168.6.36 | F4:54:33:A3:C4:60 |
| L16ER-B1BB | 192.168.6.37 | F4:54:33:A6:CE:22 |
| L16ER-B1BB | 192.168.6.38 | F4:54:33:A6:CD:FB |
| L16ER-B1BB | 192.168.6.39 | F4:54:33:A6:D4:05 |
| L30ER | 192.168.6.40 | F4:54:33:A6:37:FA |
| L16ER-B1BB | 192.168.6.41 | F4:54:33:A6:CD:8A |
| L30ER | 192.168.6.42 | F4:54:33:A3:6B:6B |
| L16ER-B1BB | 192.168.6.43 | F4:54:33:A4:6B:AE |

---

*Source: `IPADDRESSES(Sheet1).csv`, maintained on the lab SharePoint. This page is a snapshot — check the SharePoint sheet for the current authoritative version.*
