// Container state and Docker logs from stack-controller, proxied by this
// page's own nginx at /api/system/* (web/nginx.conf). Deliberately not through
// VITE_API_URL / fastapi-app, so these still work while the API is down.

async function getSystem(path) {
    const response = await fetch(`/api/system/${path}`, { cache: "no-store" });

    let body = null;
    try {
        body = await response.json();
    } catch {
        // non-JSON error page
    }

    if (!response.ok) {
        throw new Error(body?.error || body?.detail || `stack-controller returned ${response.status}`);
    }
    return body;
}

// { containers: [{ name, service, state, health: { status, failing_streak, probes }, restart_count,
//   uptime_s, exit_code, crashed, logs, watchdog: { restarts, max_restarts, gave_up, events } }] }
export async function getContainers() {
    return getSystem("containers");
}

// LogRecords (common/log_schema.py), oldest first: { records, cursor, sources, errors }
// importantOnly makes stack-controller look further back for important lines
export async function getLogs({ since = null, tail = 200, importantOnly = false } = {}) {
    const params = new URLSearchParams({ tail: String(tail) });
    if (since) {
        params.set("since", since);
    }
    if (importantOnly) {
        params.set("important_only", "true");
    }
    return getSystem(`logs?${params}`);
}
