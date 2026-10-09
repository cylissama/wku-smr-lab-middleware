import { useEffect, useRef, useState } from "react";
import StatusIndicator from "./StatusIndicator";
import { resolveWsUrl } from "../api/apiClient";

function formatTimestamp(value) {
    if (!value) return "--";
    return value;
}

export default function MessageWB({ type }) {
    const [lines, setLines] = useState([]);
    const [connected, setConnected] = useState(false);
    const [refreshTemp, setRefreshTemp] = useState(false);

    const boxRef = useRef(null);
    const capitalizeType = type.charAt(0).toUpperCase() + type.slice(1);

    // Reconnects on its own (1 s, 2 s, 4 s ... up to 30 s) whenever the socket
    // drops, e.g. while fastapi-app restarts; Refresh forces a new connection now
    useEffect(() => {
        let ws = null;
        let retryTimer = null;
        let attempt = 0;
        let closedByUs = false;

        const addLine = (line) => {
            setLines((prev) => {
                const next = [...prev, line];
                return next.length > 500 ? next.slice(-500) : next;
            });
        };

        const connect = () => {
            try {
                ws = new WebSocket(resolveWsUrl(`/ws/${type}`));
            } catch {
                setConnected(false);
                return;
            }

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);

                    if (data && data.type && data.text) {
                        addLine(data);
                    } else {
                        addLine({ text: event.data, type: "normal", timestamp: "--" });
                    }
                } catch {
                    addLine({ text: event.data, type: "normal", timestamp: "--" });
                }
            };

            ws.onopen = () => {
                attempt = 0;
                setConnected(true);
            };

            ws.onclose = () => {
                setConnected(false);
                if (!closedByUs) {
                    attempt += 1;
                    retryTimer = setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(attempt - 1, 5)));
                }
            };

            ws.onerror = () => {
                setConnected(false);
            };
        };

        connect();

        return () => {
            closedByUs = true;
            clearTimeout(retryTimer);
            ws?.close();
        };
    }, [type, refreshTemp]);

    useEffect(() => {
        boxRef.current?.scrollTo({
            top: boxRef.current.scrollHeight,
            behavior: "auto",
        });
    }, [lines]);

    return (
        <div className="flex h-full min-h-0 max-h-[32rem] w-full flex-col overflow-hidden">
            <div className="mb-3 flex items-start justify-between gap-3 border-b border-gray-200 pb-3">
                <div>
                    <h3 className="text-base font-semibold text-gray-900">
                        {capitalizeType} Messages
                    </h3>
                    <p className="text-xs text-gray-500">
                        Live message feed
                    </p>
                </div>

                <StatusIndicator
                    active={connected}
                    onMsg="Listening"
                    offMsg="Disconnected"
                />
            </div>

            <div
                ref={boxRef}
                className="min-h-0 flex-1 overflow-y-auto overflow-x-auto rounded-md bg-gray-900 p-3 font-mono text-sm text-left whitespace-pre"
            >
                {lines.length === 0 ? (
                    <p className="text-gray-400">No messages yet.</p>
                ) : (
                    lines.map((line, i) => (
                        <p
                            key={i}
                            className={`w-full whitespace-pre-wrap break-words ${
                                line.type === "error"
                                    ? "text-red-400"
                                    : line.type === "info"
                                    ? "text-yellow-400"
                                    : line.type === "live"
                                    ? "text-cyan-300"
                                    : "text-green-400"
                            }`}
                        >
                            [{formatTimestamp(line.timestamp)}] {line.text}
                        </p>
                    ))
                )}
            </div>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <div className="text-xs text-gray-500">
                    Showing up to 500 messages
                </div>

                <div className="flex flex-wrap items-center gap-2">
                    <button
                        type="button"
                        className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700"
                        onClick={() => setRefreshTemp((prev) => !prev)}
                    >
                        Refresh
                    </button>

                    <button
                        type="button"
                        className="rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-red-700"
                        onClick={() => setLines([])}
                    >
                        Clear
                    </button>
                </div>
            </div>
        </div>
    );
}
