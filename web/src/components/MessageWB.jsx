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

    useEffect(() => {
        const ws = new WebSocket(resolveWsUrl(`/ws/${type}`));

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                if (data && data.type && data.text) {
                    setLines((prev) => {
                        const next = [...prev, data];
                        return next.length > 500 ? next.slice(-500) : next;
                    });
                } else {
                    setLines((prev) => {
                        const next = [
                            ...prev,
                            { text: event.data, type: "normal", timestamp: "--" },
                        ];
                        return next.length > 500 ? next.slice(-500) : next;
                    });
                }
            } catch {
                setLines((prev) => {
                    const next = [
                        ...prev,
                        { text: event.data, type: "normal", timestamp: "--" },
                    ];
                    return next.length > 500 ? next.slice(-500) : next;
                });
            }
        };

        ws.onopen = () => {
            setConnected(true);
        };

        ws.onclose = () => {
            setConnected(false);
        };

        ws.onerror = () => {
            setConnected(false);
        };

        return () => ws.close();
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
                        Live message feed and recent history
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
                        className="rounded-md bg-slate-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition disabled:cursor-not-allowed disabled:bg-slate-400"
                        disabled
                        title="No historical message endpoint is available for this channel yet."
                    >
                        Recent Unavailable
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
