import { apiGet, getApiBaseUrl } from "./apiClient";

// fastapi-app's dependency report: { overall: "ok"|"degraded"|"starting",
// components: { db: { status, error, for_s, retry_in_s, attempts, detail }, ... },
// capture, pending_session_end, backlog } -- see fast_server/health.py
export async function getHealth() {
    return apiGet("/health");
}

// A fetch that never got a response (TypeError: Failed to fetch) means the API
// itself is unreachable, not that it answered with an error
export function describeApiError(err) {
    if (err instanceof TypeError) {
        return `Can't reach the API at ${getApiBaseUrl() || "(VITE_API_URL not set)"} — fastapi-app is stopped, restarting, or the network is down`;
    }
    return err instanceof Error ? err.message : String(err);
}
