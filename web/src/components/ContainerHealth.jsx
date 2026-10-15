import { useEffect, useState } from "react";
import { getContainers } from "../api/systemApi";
import { describeAge } from "../lib/systemHealth";
import { useNow } from "../hooks/useSystemHealth";

// Docker's own view of each AMS container (health checks, restarts), from
// stack-controller. Complements the System Health strip, which is the API's
// view of its dependencies.

function containerStatus(c) {
    if (c.state === "restarting") return { label: "restarting", tone: "amber" };
    if (!c.running) return { label: c.state ?? "stopped", tone: "red" };
    const health = c.health?.status;
    if (health === "unhealthy") return { label: "unhealthy", tone: "red" };
    if (health === "starting") return { label: "starting", tone: "amber" };
    if (health === "healthy") return { label: "healthy", tone: "green" };
    return { label: "running", tone: "gray" };
}

const DOTS = {
    green: "bg-green-500",
    amber: "bg-amber-500 animate-pulse",
    red: "bg-red-500 animate-pulse",
    gray: "bg-gray-400",
};

const TEXT = {
    green: "text-green-700",
    amber: "text-amber-700",
    red: "text-red-700",
    gray: "text-gray-600",
};

function lastProbe(c) {
    const probes = c.health?.probes ?? [];
    return probes[probes.length - 1] ?? null;
}

function formatEpoch(seconds) {
    return seconds ? new Date(seconds * 1000).toLocaleTimeString() : "--";
}

function ContainerRow({ c, now, expanded, onToggle, onShowLogs }) {
    const status = containerStatus(c);
    const probe = lastProbe(c);
    const finishedAgo = c.finished_at ? describeAge(now / 1000 - c.finished_at) : null;

    return (
        <li className="rounded-lg border border-gray-200">
            <button type="button" className="w-full px-3 py-2 text-left hover:bg-gray-50" onClick={onToggle}>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                    <span className={`inline-block h-2.5 w-2.5 rounded-full ${DOTS[status.tone]}`}></span>
                    <span className="w-36 font-medium text-gray-900">{c.service}</span>
                    <span className={`w-20 ${TEXT[status.tone]}`}>{status.label}</span>
                    <span className="text-xs text-gray-500">
                        {c.running
                            ? `up ${describeAge(c.uptime_s)}`
                            : `exit ${c.exit_code}${finishedAgo ? ` · ${finishedAgo} ago` : ""}`}
                    </span>
                    {c.restart_count > 0 && <span className="text-xs text-amber-700">restarts {c.restart_count}</span>}
                    {c.health?.failing_streak > 0 && (
                        <span className="text-xs text-red-700">failing {c.health.failing_streak}×</span>
                    )}
                    {c.watchdog?.gave_up ? (
                        <span className="text-xs font-semibold text-red-700">watchdog gave up — needs a person</span>
                    ) : c.watchdog?.restarts > 0 ? (
                        <span className="text-xs text-amber-700">
                            watchdog {c.watchdog.restarts}/{c.watchdog.max_restarts}
                        </span>
                    ) : null}
                    <span className="ml-auto text-xs text-gray-400">{expanded ? "▾" : "▸"}</span>
                </div>
                {(probe?.output || c.error) && (
                    <p
                        className={`mt-1 truncate pl-5 font-mono text-xs ${
                            probe?.exit_code === 0 ? "text-gray-500" : "text-red-700"
                        }`}
                    >
                        {c.error || probe.output}
                    </p>
                )}
            </button>

            {expanded && (
                <div className="space-y-3 border-t border-gray-100 px-3 py-2 text-xs">
                    {c.health?.probes?.length > 0 && (
                        <div>
                            <h4 className="mb-1 font-semibold text-gray-600">Last health checks</h4>
                            <ul className="space-y-0.5 font-mono">
                                {c.health.probes.map((p, i) => (
                                    <li key={i} className={p.exit_code === 0 ? "text-gray-600" : "text-red-700"}>
                                        <span className="text-gray-400">{formatEpoch(p.start)}</span> exit {p.exit_code}
                                        {p.output ? ` — ${p.output}` : ""}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {c.watchdog?.events?.length > 0 && (
                        <div>
                            <h4 className="mb-1 font-semibold text-gray-600">Watchdog</h4>
                            <ul className="space-y-0.5">
                                {c.watchdog.events.map((e, i) => (
                                    <li key={i} className="text-amber-800">
                                        <span className="text-gray-400">{formatEpoch(e.time)}</span> {e.message}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {c.logs?.length > 0 && (
                        <div>
                            <h4 className="mb-1 font-semibold text-gray-600">Last log lines before it stopped</h4>
                            <pre className="max-h-48 overflow-auto rounded bg-gray-900 p-2 text-[11px] whitespace-pre-wrap break-words text-gray-100">
                                {c.logs.map((r) => `${r.ts?.slice(11, 19) ?? ""} ${r.level_name} ${r.message}`).join("\n")}
                            </pre>
                        </div>
                    )}

                    <div className="flex flex-wrap items-center gap-3 text-gray-500">
                        <span>container {c.name}</span>
                        <span>image {c.image}</span>
                        {!c.autoheal && <span>not auto-restarted</span>}
                        <button
                            type="button"
                            className="ml-auto rounded border border-gray-200 px-2 py-0.5 text-gray-700 hover:bg-gray-50"
                            onClick={() => onShowLogs?.(c.service)}
                        >
                            Show logs
                        </button>
                    </div>
                </div>
            )}
        </li>
    );
}

export default function ContainerHealth({ onShowLogs }) {
    const now = useNow(1000);
    const [state, setState] = useState({ containers: [], error: "", lastOk: null, loading: true });
    const [toggled, setToggled] = useState(() => new Set());

    useEffect(() => {
        let cancelled = false;

        const load = async () => {
            try {
                const data = await getContainers();
                if (!cancelled) {
                    setState({ containers: data.containers ?? [], error: "", lastOk: Date.now(), loading: false });
                }
            } catch (err) {
                if (!cancelled) {
                    const message = err instanceof Error ? err.message : String(err);
                    setState((prev) => ({ ...prev, error: message, loading: false }));
                }
            }
        };

        load();
        const intervalId = setInterval(load, 10000);
        return () => {
            cancelled = true;
            clearInterval(intervalId);
        };
    }, []);

    const toggle = (name) =>
        setToggled((prev) => {
            const next = new Set(prev);
            if (next.has(name)) next.delete(name);
            else next.add(name);
            return next;
        });

    const problems = state.containers.filter((c) => containerStatus(c).tone === "red").length;

    return (
        <div className="flex h-full min-w-0 flex-col">
            <div className="mb-3 flex items-start justify-between gap-3 border-b border-gray-200 pb-3">
                <div>
                    <h3 className="text-base font-semibold text-gray-900">Container Health</h3>
                    <p className="text-xs text-gray-500">Docker health checks and restarts, per container</p>
                </div>
                <span className={`text-xs ${problems ? "font-semibold text-red-700" : "text-gray-400"}`}>
                    {problems
                        ? `${problems} need${problems === 1 ? "s" : ""} attention`
                        : state.lastOk
                          ? `updated ${describeAge((now - state.lastOk) / 1000)} ago`
                          : ""}
                </span>
            </div>

            {state.error && (
                <p className="mb-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
                    {state.error}
                    {state.containers.length > 0 ? " — showing the last known state." : ""}
                </p>
            )}

            {state.loading && <p className="text-sm text-gray-500">Loading containers...</p>}

            <ul className="space-y-2 overflow-y-auto">
                {state.containers.map((c) => (
                    <ContainerRow
                        key={c.name}
                        c={c}
                        now={now}
                        // Crashed containers start open (their log tail is the explanation);
                        // a click flips whatever the default is
                        expanded={c.crashed !== toggled.has(c.name)}
                        onToggle={() => toggle(c.name)}
                        onShowLogs={onShowLogs}
                    />
                ))}
            </ul>
        </div>
    );
}
