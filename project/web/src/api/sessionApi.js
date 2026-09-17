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

export async function startSessionByLabel(label, isTestSession = true, sessionLabel) {
    const encodedLabel = encodeURIComponent(label);
    const encodedIsTestSession = encodeURIComponent(String(Boolean(isTestSession)));
    const encodedSessionLabel = encodeURIComponent(sessionLabel);
    return apiGet(
        `/session/start/${encodedLabel}?is_test_session=${encodedIsTestSession}&session_label=${encodedSessionLabel}`
    );
}

export async function stopSessionRequest() {
    // return apiGet("/session/stop/");
    return  apiGet("/session/stop");


}
