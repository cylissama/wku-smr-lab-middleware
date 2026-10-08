import { apiGet, apiPost } from "./apiClient";

// Capture mode: "idle" | "monitor" | "record" | "stopping"
export async function getCapture() {
    return apiGet("/capture");
}

// Monitor (listen-only) mode: edge devices run and live data shows on the
// dashboard, but nothing is stored
export async function startListening() {
    return apiPost("/listen/start");
}

export async function stopListening() {
    return apiPost("/listen/stop");
}
