import { useSyncExternalStore } from "react";

// Errors the dashboard itself runs into (failed requests, API unreachable),
// kept in the browser so they're visible even when nothing server-side is.
// Records use the same shape as the server's LogRecord (common/log_schema.py)
// with source "dashboard", so the Logs box can merge them in.

const MAX_EVENTS = 50;
const LEVELS = { 10: "DEBUG", 20: "INFO", 30: "WARNING", 40: "ERROR", 50: "CRITICAL" };

let events = [];
let seq = 0;
const listeners = new Set();

function emit() {
    for (const listener of listeners) {
        listener();
    }
}

export function reportDashboardEvent(message, level = 40, category = "system") {
    const last = events[events.length - 1];

    // Repeats of the same message (e.g. a failing poll) collapse into one row
    if (last && last.message === message && last.level === level) {
        events = [...events.slice(0, -1), { ...last, count: last.count + 1, ts: new Date().toISOString() }];
    } else {
        seq += 1;
        const record = {
            id: `dashboard:${Date.now()}:${seq}`,
            ts: new Date().toISOString(),
            source: "dashboard",
            logger: "dashboard",
            level,
            level_name: LEVELS[level] ?? String(level),
            priority: null,
            category,
            important: level >= 30,
            message,
            context: {},
            count: 1,
        };
        events = [...events, record].slice(-MAX_EVENTS);
    }
    emit();
}

export function reportDashboardError(message) {
    reportDashboardEvent(message, 40);
}

function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
}

function getSnapshot() {
    return events;
}

export function useDashboardEvents() {
    return useSyncExternalStore(subscribe, getSnapshot);
}
