import { useDashboardEvents } from "../api/dashboardEvents";
import { useNow } from "../hooks/useSystemHealth";
import { COMPONENT_LABELS, componentEntries, describeAge, healthProblems } from "../lib/systemHealth";

const STATUS_STYLES = {
    ok: { chip: "border-green-200 bg-green-50 text-green-800", dot: "bg-green-500" },
    down: { chip: "border-red-300 bg-red-50 text-red-800", dot: "bg-red-500 animate-pulse" },
    unknown: { chip: "border-gray-200 bg-gray-50 text-gray-600", dot: "bg-gray-400" },
    stale: { chip: "border-gray-200 bg-gray-50 text-gray-400", dot: "bg-gray-300" },
};

function formatTime(iso) {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? "--" : date.toLocaleTimeString();
}

function Chip({ name, component, stale }) {
    const style = STATUS_STYLES[stale ? "stale" : component.status] ?? STATUS_STYLES.unknown;
    const title =
        component.status === "down"
            ? `${component.error} (down ${describeAge(component.for_s)})`
            : component.status === "ok"
              ? "OK"
              : "Not connected yet";

    return (
        <span
            className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium ${style.chip}`}
            title={title}
        >
            <span className={`inline-block h-2 w-2 rounded-full ${style.dot}`}></span>
            {COMPONENT_LABELS[name] ?? name}
        </span>
    );
}

// One-line summary for the sticky session box: overall state + a chip per
// dependency, and a toggle for the details card
export function HealthStrip({ health, apiError, lastContact, loading, expanded, onToggle }) {
    const now = useNow(1000);
    const problems = healthProblems({ health, apiError });

    let summary;
    let summaryClass;
    if (loading && !health) {
        summary = "Checking system health...";
        summaryClass = "text-gray-500";
    } else if (apiError) {
        summary = "API unreachable";
        summaryClass = "text-red-700";
    } else if (problems.length > 0) {
        summary = `Degraded — ${problems.join(", ")} down`;
        summaryClass = "text-red-700";
    } else if (health?.overall === "ok") {
        summary = "All systems OK";
        summaryClass = "text-green-700";
    } else {
        summary = "Starting up...";
        summaryClass = "text-amber-700";
    }

    return (
        <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold text-gray-700">System:</span>
            <span className={`font-medium ${summaryClass}`}>{summary}</span>

            <div className="flex flex-wrap items-center gap-1.5">
                {componentEntries(health).map(([name, component]) => (
                    <Chip key={name} name={name} component={component} stale={Boolean(apiError)} />
                ))}
            </div>

            <span className="ml-auto text-xs text-gray-400">
                {lastContact ? `updated ${describeAge((now - lastContact) / 1000)} ago` : ""}
            </span>
            {onToggle && (
                <button
                    type="button"
                    className="rounded-md border border-gray-200 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
                    onClick={onToggle}
                >
                    {expanded ? "Hide details" : "Details"}
                </button>
            )}
        </div>
    );
}

// Full explanation of what's wrong: shown automatically while anything is
// down, or when opened from the strip
export function HealthDetails({ health, apiError, lastContact }) {
    const now = useNow(1000);
    const events = useDashboardEvents();
    const down = componentEntries(health).filter(([, c]) => c.status !== "ok");
    const backlog = Object.entries(health?.backlog ?? {});
    const recentEvents = events.filter((e) => e.level >= 30).slice(-5).reverse();

    return (
        <div className="mb-6 rounded-xl border border-gray-200 bg-white p-4 shadow-sm lg:p-5">
            <h2 className="mb-3 text-base font-semibold text-gray-900">System Health</h2>

            {apiError && (
                <div className="mb-3 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
                    <p className="font-semibold">API (fastapi-app) unreachable</p>
                    <p>{apiError}</p>
                    <p className="mt-1 text-xs text-red-700">
                        Last contact: {lastContact ? `${describeAge((now - lastContact) / 1000)} ago` : "never"}.
                        Sessions can't be started or stopped until it's back; it restarts on its own if it crashed.
                        Container Health and Logs at the bottom of the page show why.
                        {health ? " The statuses below are from before it went away." : ""}
                    </p>
                </div>
            )}

            {down.length === 0 && !apiError && health && (
                <p className="text-sm text-green-700">Every dependency is up.</p>
            )}

            {down.length > 0 && (
                <ul className="space-y-2">
                    {down.map(([name, c]) => (
                        <li key={name} className="rounded-lg border border-gray-200 px-3 py-2 text-sm">
                            <div className="flex flex-wrap items-center gap-2">
                                <Chip name={name} component={c} stale={Boolean(apiError)} />
                                <span className="text-gray-700">
                                    {c.status === "down" ? `down ${describeAge(c.for_s)}` : "not connected yet"}
                                </span>
                                {c.retry_in_s !== null && c.retry_in_s !== undefined && (
                                    <span className="text-xs text-gray-500">retrying in {describeAge(c.retry_in_s)}</span>
                                )}
                                {c.attempts > 0 && (
                                    <span className="text-xs text-gray-500">attempt {c.attempts}</span>
                                )}
                            </div>
                            {c.error && <p className="mt-1 break-words font-mono text-xs text-red-700">{c.error}</p>}
                        </li>
                    ))}
                </ul>
            )}

            {health?.pending_session_end && (
                <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    Session {health.pending_session_end} was stopped while the database was down. Its end time will be
                    saved as soon as the database is back.
                </p>
            )}

            {backlog.length > 0 && (
                <ul className="mt-3 space-y-1 text-sm text-amber-800">
                    {backlog.map(([name, b]) => (
                        <li key={name}>
                            {name} inserts failing for {describeAge(now / 1000 - b.since)}
                            {b.dropped ? ` — ${b.dropped} rows dropped` : " — rows held in memory until the database is back"}
                        </li>
                    ))}
                </ul>
            )}

            {recentEvents.length > 0 && (
                <div className="mt-4">
                    <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
                        Recent dashboard errors
                    </h3>
                    <ul className="space-y-1 font-mono text-xs text-gray-700">
                        {recentEvents.map((e) => (
                            <li key={e.id} className="break-words">
                                <span className="text-gray-400">{formatTime(e.ts)}</span> {e.message}
                                {e.count > 1 ? <span className="text-gray-400"> (×{e.count})</span> : null}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
}
