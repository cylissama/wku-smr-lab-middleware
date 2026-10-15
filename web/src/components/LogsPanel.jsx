import { useEffect, useMemo, useRef, useState } from "react";
import { getLogs } from "../api/systemApi";
import { useDashboardEvents } from "../api/dashboardEvents";

// Recent Docker logs of every AMS container plus the dashboard's own errors,
// all as LogRecords (common/log_schema.py). "Important" shows records marked
// important and anything WARNING or worse. Records carry a reserved
// `priority`; its badge and filter appear only once something sets it.

const MAX_RECORDS = 1000;
const POLL_MS = 3000;

const LEVEL_STYLES = {
    DEBUG: "bg-gray-100 text-gray-500",
    INFO: "bg-sky-50 text-sky-700",
    WARNING: "bg-amber-50 text-amber-800",
    ERROR: "bg-red-50 text-red-700",
    CRITICAL: "bg-red-600 text-white",
};

const LEVEL_FILTERS = [
    { value: 0, label: "All levels" },
    { value: 20, label: "Info and up" },
    { value: 30, label: "Warnings and up" },
    { value: 40, label: "Errors only" },
];

function formatTime(iso) {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? "--:--:--" : date.toLocaleTimeString();
}

// New records merged in by id (a poll's `since` overlaps the previous one),
// kept in time order and capped
function mergeRecords(existing, incoming) {
    if (incoming.length === 0) return existing;
    const byId = new Map(existing.map((r) => [r.id, r]));
    for (const r of incoming) {
        byId.set(r.id, r);
    }
    return [...byId.values()].sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0)).slice(-MAX_RECORDS);
}

function LogRow({ r }) {
    const [open, setOpen] = useState(false);
    const [firstLine, ...rest] = String(r.message).split("\n");
    const hasContext = r.context && Object.keys(r.context).length > 0;
    const expandable = rest.length > 0 || hasContext;

    return (
        <li className="border-b border-gray-800 py-0.5 last:border-0">
            <div
                className={`flex gap-2 ${expandable ? "cursor-pointer" : ""}`}
                onClick={expandable ? () => setOpen((v) => !v) : undefined}
            >
                <span className="shrink-0 text-gray-500">{formatTime(r.ts)}</span>
                <span
                    className={`w-16 shrink-0 rounded px-1 text-center text-[10px] font-semibold leading-4 ${
                        LEVEL_STYLES[r.level_name] ?? LEVEL_STYLES.INFO
                    }`}
                >
                    {r.level_name}
                </span>
                {r.priority !== null && r.priority !== undefined && (
                    <span className="shrink-0 rounded bg-purple-600 px-1 text-[10px] font-semibold leading-4 text-white">
                        P{r.priority}
                    </span>
                )}
                <span className="w-28 shrink-0 truncate text-cyan-300" title={r.source}>
                    {r.source}
                </span>
                <span className="min-w-0 flex-1 break-words text-gray-100">
                    {expandable && <span className="text-gray-500">{open ? "▾ " : "▸ "}</span>}
                    {firstLine}
                    {r.count > 1 ? <span className="text-gray-500"> (×{r.count})</span> : null}
                </span>
            </div>
            {open && (
                <pre className="mt-1 ml-[5.5rem] whitespace-pre-wrap break-words text-[11px] text-gray-300">
                    {rest.join("\n")}
                    {hasContext ? `${rest.length ? "\n" : ""}${JSON.stringify(r.context)}` : ""}
                </pre>
            )}
        </li>
    );
}

export default function LogsPanel({ focusSource, onFocusHandled }) {
    const [records, setRecords] = useState([]);
    const [sources, setSources] = useState([]);
    const [error, setError] = useState("");
    const [tab, setTab] = useState("important");
    const [source, setSource] = useState("all");
    const [minLevel, setMinLevel] = useState(0);
    const [paused, setPaused] = useState(false);
    const cursor = useRef(null);
    const boxRef = useRef(null);
    const dashboardEvents = useDashboardEvents();

    // "Show logs" from the Container Health box jumps here filtered to that container
    useEffect(() => {
        if (focusSource) {
            setSource(focusSource);
            setTab("all");
            boxRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
            onFocusHandled?.();
        }
    }, [focusSource, onFocusHandled]);

    useEffect(() => {
        if (paused) return undefined;
        let cancelled = false;

        const poll = async () => {
            try {
                const first = !cursor.current;
                const [data, important] = await Promise.all([
                    getLogs({ since: cursor.current, tail: first ? 300 : 500 }),
                    // On the first load, also fetch older important lines that the
                    // last 300 routine ones would have pushed out
                    first ? getLogs({ tail: 300, importantOnly: true }) : null,
                ]);
                if (cancelled) return;
                if (data.cursor) cursor.current = data.cursor;
                setSources(data.sources ?? []);
                setRecords((prev) =>
                    mergeRecords(mergeRecords(prev, important?.records ?? []), data.records ?? []),
                );
                setError(
                    Object.keys(data.errors ?? {}).length
                        ? `Couldn't read logs from: ${Object.entries(data.errors).map(([s, e]) => `${s} (${e})`).join(", ")}`
                        : "",
                );
            } catch (err) {
                if (!cancelled) setError(err instanceof Error ? err.message : String(err));
            }
        };

        poll();
        const intervalId = setInterval(poll, POLL_MS);
        return () => {
            cancelled = true;
            clearInterval(intervalId);
        };
    }, [paused]);

    const shown = useMemo(() => {
        const all = mergeRecords(records, dashboardEvents);
        return all.filter(
            (r) =>
                (tab === "all" || r.important || r.level >= 30) &&
                (source === "all" || r.source === source) &&
                r.level >= minLevel,
        );
    }, [records, dashboardEvents, tab, source, minLevel]);

    // Follow new lines unless the reader has scrolled up
    useEffect(() => {
        const box = boxRef.current;
        if (!box || paused) return;
        const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
        if (nearBottom) box.scrollTop = box.scrollHeight;
    }, [shown, paused]);

    const sourceOptions = [...new Set([...sources, ...(dashboardEvents.length ? ["dashboard"] : [])])].sort();

    return (
        <div className="flex h-full min-h-0 min-w-0 flex-col">
            <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-gray-200 pb-3">
                <div className="mr-auto">
                    <h3 className="text-base font-semibold text-gray-900">Logs</h3>
                    <p className="text-xs text-gray-500">Docker logs of every AMS container and dashboard errors</p>
                </div>

                <div className="flex overflow-hidden rounded-md border border-gray-200 text-xs">
                    {[
                        ["important", "Important"],
                        ["all", "All"],
                    ].map(([value, label]) => (
                        <button
                            key={value}
                            type="button"
                            className={`px-2.5 py-1 ${tab === value ? "bg-cyan-600 text-white" : "bg-white text-gray-700 hover:bg-gray-50"}`}
                            onClick={() => setTab(value)}
                        >
                            {label}
                        </button>
                    ))}
                </div>

                <select
                    className="rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700"
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                >
                    <option value="all">All sources</option>
                    {sourceOptions.map((s) => (
                        <option key={s} value={s}>
                            {s}
                        </option>
                    ))}
                </select>

                <select
                    className="rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700"
                    value={minLevel}
                    onChange={(e) => setMinLevel(Number(e.target.value))}
                >
                    {LEVEL_FILTERS.map((f) => (
                        <option key={f.value} value={f.value}>
                            {f.label}
                        </option>
                    ))}
                </select>

                <button
                    type="button"
                    className={`rounded-md border px-2.5 py-1 text-xs ${
                        paused ? "border-amber-300 bg-amber-50 text-amber-800" : "border-gray-200 text-gray-700 hover:bg-gray-50"
                    }`}
                    onClick={() => setPaused((p) => !p)}
                >
                    {paused ? "Resume" : "Pause"}
                </button>
            </div>

            {error && (
                <p className="mb-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>
            )}

            <div
                ref={boxRef}
                className="min-h-0 flex-1 overflow-y-auto rounded-md bg-gray-900 p-2 font-mono text-xs"
                style={{ maxHeight: "28rem" }}
            >
                {shown.length === 0 ? (
                    <p className="text-gray-400">
                        {tab === "important" ? "Nothing important logged recently." : "No log lines yet."}
                    </p>
                ) : (
                    <ul>
                        {shown.map((r) => (
                            <LogRow key={r.id} r={r} />
                        ))}
                    </ul>
                )}
            </div>

            <p className="mt-2 text-xs text-gray-500">
                Showing {shown.length} of the last {Math.min(records.length + dashboardEvents.length, MAX_RECORDS)} lines
                {paused ? " · paused" : ""}
            </p>
        </div>
    );
}
