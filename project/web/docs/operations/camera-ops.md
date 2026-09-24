# Camera Live Feed

How to view a live feed from any of the camera nodes


## Use case

You may want to receive a live feed of data from the camera when mounting or setting up the camera edge node at a certain angle. This method has been used when trying to mount the edge node in a position so that the camera can view multiple Aruco markers at once.

## Requirements

- Camera edge node setup complete
- install ffmpeg on the camera edge node
- a separate device on the network
    - with [VLC](https://www.videolan.org) media player installed


## Steps to stream a live feed from the camera node

- Step 1: ssh into the camera edge node
- Step 2: run the following command 

```
ffmpeg -f v4l2 -input_format mjpeg -video_size <WIDTH>x<HEIGHT> -framerate <FPS> -i <VIDEO_DEVICE> -f mjpeg -listen 1 -multiple_requests 1 http://0.0.0.0:<PORT>/<STREAM_PATH>
```

for example

```
ffmpeg -f v4l2 -input_format mjpeg -video_size 1920x1080 -framerate 15 -i /dev/video0 -f mjpeg -listen 1 -multiple_requests 1 http://0.0.0.0:8090/stream.mjpg
```

## Flag reference
 
| Flag | Meaning |
|---|---|
| `-f v4l2` | Reads the camera input using Video4Linux2, the Linux kernel interface for camera devices. |
| `-input_format mjpeg` | Requests frames already MJPEG-encoded by the camera hardware, reducing CPU load on the edge node. |
| `-video_size <WIDTH>x<HEIGHT>` | Capture resolution, e.g. `1920x1080`. |
| `-framerate <FPS>` | Capture frame rate in frames per second, e.g. `15`. |
| `-i <VIDEO_DEVICE>` | Path to the camera device, e.g. `/dev/video0`. |
| `-f mjpeg` *(second occurrence)* | Sets the **output** format/container to MJPEG. |
| `-listen 1` | Runs ffmpeg as an HTTP server that waits for an incoming connection, rather than pushing the stream to a remote host. |
| `-multiple_requests 1` | Lets the server accept further requests instead of exiting after the first client disconnects. |
| `http://0.0.0.0:<PORT>/<STREAM_PATH>` | The address ffmpeg binds and listens on. `0.0.0.0` means "all network interfaces" — it is **not** an address a viewer connects to. `<PORT>` is the TCP port (e.g. `8090`); `<STREAM_PATH>` is the URL path clients request (e.g. `stream.mjpg`). |
 
## Placeholders to fill in
 
| Placeholder | Description |
|---|---|
| `<WIDTH>x<HEIGHT>` | Capture resolution |
| `<FPS>` | Capture frame rate |
| `<VIDEO_DEVICE>` | Camera device path (list devices with `v4l2-ctl --list-devices`) |
| `<PORT>` | TCP port to serve the stream on |
| `<STREAM_PATH>` | URL path for the stream |
| `<EDGE_NODE_IP>` | LAN IP of the edge node — used by viewers, not part of this command |

## Notes

This seems to work best at a lower frame rate, such as 10 fps, sometimes 15.

Also attempt to use at a lower capture resolution to reduce latency.

## To view the Stream on a separate device on the same network

- Open VLC media player on the device
- File -> Open Network
- When prompted to input a URL use

```
http://<EDGE_NODE_IP>:<PORT>/<STREAM_PATH>
```
 
Example: `http://192.168.1.42:8090/stream.mjpg`