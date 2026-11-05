import { apiGet, apiPost } from "./apiClient";

// Capture mode: "idle" | "monitor" | "record" | "stopping"
export async function getCapture() {
    return apiGet("/capture");
}

// Selectable devices with their state: [{ key: "imu/106", category, device_label,
// service, stack, state, db_id, joint, node, ip }] (db_id: device.id in the
// database; joint: e.g. "J1" for IMUs; node/ip: the Swarm node it's pinned to
// and its address; each null when unknown)
export async function getDevices() {
    return apiGet("/devices");
}

// Monitor (listen-only) mode: edge devices run and live data shows on the
// dashboard, but nothing is stored. devices: device keys, or null for all.
export async function startListening(devices = null) {
    return apiPost("/listen/start", { devices });
}

export async function stopListening() {
    return apiPost("/listen/stop");
}
