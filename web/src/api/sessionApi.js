import { apiGet } from "./apiClient";

export async function getSessionStatus() {
    return apiGet("/session");
}

export async function getSessions() {
    return apiGet("/sessions");
}

export async function getSessionLabels() {
    return apiGet("/session/labels");
}

// devices: device keys to record (e.g. ["imu/106", "robot/main"]), or null for all
export async function startSessionByLabel(label, isTestSession = true, sessionLabel, devices = null) {
    const encodedLabel = encodeURIComponent(label);
    const encodedIsTestSession = encodeURIComponent(String(Boolean(isTestSession)));
    const encodedSessionLabel = encodeURIComponent(sessionLabel);
    const deviceParams = (devices ?? []).map((key) => `&devices=${encodeURIComponent(key)}`).join("");
    return apiGet(
        `/session/start/${encodedLabel}?is_test_session=${encodedIsTestSession}&session_label=${encodedSessionLabel}${deviceParams}`
    );
}

export async function stopSessionRequest() {
    // return apiGet("/session/stop/");
    return  apiGet("/session/stop");


}
