// fastapi-app's dependencies, as reported by GET /health (fast_server/health.py)
export const COMPONENT_LABELS = {
    db: "Database",
    mqtt: "MQTT broker",
    stack_controller: "Stack controller",
    tcp: "Robot TCP server",
    logs: "Log files",
    backups: "Backup folder",
    plc: "PLC (robot done)",
};

export function describeAge(seconds) {
    if (seconds === null || seconds === undefined) return "--";
    const s = Math.max(0, Math.round(seconds));
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function componentEntries(health) {
    return Object.entries(health?.components ?? {});
}

// Problems worth a person's attention: the API itself, or any component down
export function healthProblems({ health, apiError }) {
    if (apiError) return ["API"];
    return componentEntries(health)
        .filter(([, c]) => c.status === "down")
        .map(([name]) => COMPONENT_LABELS[name] ?? name);
}
