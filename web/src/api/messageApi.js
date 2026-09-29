import { apiPost } from "./apiClient";

export async function sendDashboardMessage(dest, type, text) {
    return apiPost(`/send/${dest}`, { type, text });
}