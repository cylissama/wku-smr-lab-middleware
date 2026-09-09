import { apiGet } from "./apiClient";

export async function getSessionStatus() {
    return apiGet("/session");
}

export async function getSessions() {
    return apiGet("/sessions");
}

export async function startSessionByLabel(label, isTestSession = true) {
    const encodedLabel = encodeURIComponent(label);
    const encodedIsTestSession = encodeURIComponent(String(Boolean(isTestSession)));
    return apiGet(`/session/start/${encodedLabel}?is_test_session=${encodedIsTestSession}`);
}

export async function stopSessionRequest() {
    // return apiGet("/session/stop/");
    return  apiGet("/session/stop");


}
