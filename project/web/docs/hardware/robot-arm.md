# FANUC Robot Arm

## Streaming the data

A robot arm streams joint angles and TCP (tool center point) pose as CSV lines over a raw TCP connection to the `tcp_server`, rather than over MQTT. Unlike the other devices, the robot is started manually by a human operator in the lab — it is not remotely orchestrated. See [TCP Server](/docker/tcp-server) for how the container on the other end of that connection listens, batches, and stores this data.

# Robot Joint & Pose Data Format

| Field | Type | Description | Example Value |
|---|---|---|---|
| `id` | Integer | Unique row identifier for the record | `398479` |
| `ts_epoch` | Integer (epoch s) | Timestamp of the robot controller clock at time of sample | `1552447821` |
| `joint_1` | Float | Joint 1 angle/position (likely degrees) | `0.001674` |
| `joint_2` | Float | Joint 2 angle/position (likely degrees) | `0.001414` |
| `joint_3` | Float | Joint 3 angle/position (likely degrees) | `-0.001159` |
| `joint_4` | Float | Joint 4 angle/position (likely degrees) | `0.000825` |
| `joint_5` | Float | Joint 5 angle/position (likely degrees) | `-90.000511` |
| `joint_6` | Float | Joint 6 angle/position (likely degrees) | `-0.000624` |
| `x` | Float | Tool center point (TCP) position, X-axis (likely mm) | `1783.12` |
| `y` | Float | Tool center point (TCP) position, Y-axis (likely mm) | `-2205.959` |
| `z` | Float | Tool center point (TCP) position, Z-axis (likely mm) | `928.974` |
| `w` | Float | TCP orientation, yaw component (likely degrees) | `179.999` |
| `p` | Float | TCP orientation, pitch component (likely degrees) | `0.001` |
| `r` | Float | TCP orientation, roll component (likely degrees) | `0.001` |
| `recorded_at` | Float (epoch s) | Timestamp when the sample was recorded | `1775679035.11709` |
| `ingested_at` | Float (epoch s) | Timestamp when the record was ingested into the system | `1775679035.298104` |
| `device_id` | Integer | Identifier of the robot/device | `2` |
| `session_id` | Integer | Identifier of the recording session | `318` |
| `frame_id` | Integer | Frame/sequence identifier for the sample | `1` |

## Code behind the robot

The robots configuration is done on the teach pendant located alongside the robot controller in the SMR Lab space downstairs.

This teach pendant is where the operator can set Client (C) and Server (S) tags. The **C** Tags are used to point the robot to the AMS' network location. Currently we do not make use of the **S** tags.

The Karel codes then use these tags during runtime to send data.


## Karel Code 

This is the code that is called on robot startup to initialize data points and send to the **C1** tag IP on port 5001. 

```karel
PROGRAM stream_pos

%NOLOCKGROUP
%NOPAUSE = ERROR + COMMAND + TPENABLE
%COMMENT = 'CSV -> C1 tag (simple inline)'

VAR
  st   : INTEGER;
  jp   : JOINTPOS;
  cp   : XYZWPR;
  j    : ARRAY[9] OF REAL;
  sock : FILE;

  t_int  : INTEGER;
  ts_str : STRING[32];
  c_str  : STRING[16];

  s_pre  : STRING[128];
  s_post : STRING[254];
  eol    : STRING[2];
  count  : INTEGER;

ROUTINE rts(val : REAL; digs : INTEGER; decs : INTEGER) : STRING
VAR out : STRING[32]
BEGIN
  CNV_REAL_STR(val, digs, decs, out);
  RETURN(out);
END rts;

BEGIN
  eol = CHR(13) + CHR(10);
  count = 0; -- Initialize the counter

  MSG_CONNECT('C1:', st);
  OPEN FILE sock('RW','C1:');
  IF IO_STATUS(sock) <> 0 THEN
    WRITE('OPEN C1 failed (will retry after first write)'); WRITE(eol);
  ENDIF;

  -- Reordered header (same fields, new order)
  WRITE sock('count,ts_int,ts_str,J1,J2,J3,J4,J5,J6,X,Y,Z,W,P,R'); WRITE sock(eol);

  WHILE TRUE DO
    count = count + 1; -- Increment every loop

    jp = CURJPOS(1, st);
    cp = CURPOS(1, st);
    CNV_JPOS_REL(jp, j, st);

    GET_TIME(t_int);
    CNV_TIME_STR(t_int, ts_str);

    -- Convert the integer count to a string
    CNV_INT_STR(count, 1, 10, c_str)

    -- Start of CSV line: count,
    s_pre  = c_str + ',';

    -- Rest of fields (starts with a comma): J1..J6, X..R
    s_post = ',' +
             rts(j[1],3,6) + ',' + rts(j[2],3,6) + ',' + rts(j[3],3,6) + ',' +
             rts(j[4],3,6) + ',' + rts(j[5],3,6) + ',' + rts(j[6],3,6) + ',' +
             rts(cp.x,3,3) + ',' + rts(cp.y,3,3) + ',' + rts(cp.z,3,3) + ',' +
             rts(cp.w,3,3) + ',' + rts(cp.p,3,3) + ',' + rts(cp.r,3,3);

    -- Write in new order: count, ts_int, ts_str, (then rest)
    WRITE sock(s_pre);
    WRITE sock(t_int);
    WRITE sock(',');
    WRITE sock(ts_str);
    WRITE sock(s_post);
    WRITE sock(eol);

    IF IO_STATUS(sock) <> 0 THEN
      DELAY 200;
      CLOSE FILE sock;
      MSG_DISCO('C1:', st);
      MSG_CONNECT('C1:', st);
      OPEN FILE sock('RW','C1:');

      IF IO_STATUS(sock) = 0 THEN
        -- Reordered header on reconnect too
        WRITE sock('count,ts_int,ts_str,J1,J2,J3,J4,J5,J6,X,Y,Z,W,P,R'); WRITE sock(eol);
      ENDIF;
    ENDIF;

    DELAY 50;
  ENDWHILE;

  CLOSE FILE sock;
  MSG_DISCO('C1:', st);
END stream_pos;
```

## Notes

- `joint_1`–`joint_6` correspond to a 6-axis robot arm's joint positions; units are inferred as degrees (worth confirming against the robot's controller docs).
- `x, y, z, w, p, r` follow a common industrial-robot TCP pose convention (position in mm + orientation as yaw/pitch/roll or similar), but the exact orientation convention should be confirmed against the robot manufacturer's spec.
- `ts_epoch` vs `recorded_at` both appear to be timestamps — `ts_epoch` looks like it may update only per motion segment (repeated across rows) while `recorded_at` is per-sample.