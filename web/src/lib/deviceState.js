// Shared by the Devices box and the device rail, so both show the same colors

export const CATEGORY_ORDER = ["imu", "camera", "robot"];
export const CATEGORY_NAMES = { imu: "IMU", camera: "Camera", robot: "Robot" };

// Status tones: grey = offline, red = fault, blue = standby, green = sending data
export const TONE_COLORS = {
    grey: "#64748b",
    red: "#ef4444",
    blue: "#3b82f6",
    green: "#22c55e",
};

export const TONE_DOTS = {
    grey: "bg-slate-400",
    red: "bg-red-500",
    blue: "bg-blue-500",
    green: "bg-green-500 animate-pulse",
};

// Device state (from GET /devices) -> tone and text
const STATE_STYLES = {
    running: { tone: "blue", text: "running", caption: "STANDBY" },
    connected: { tone: "blue", text: "connected", caption: "STANDBY" },
    deploying: { tone: "blue", text: "starting", caption: "STARTING" },
    removing: { tone: "blue", text: "stopping", caption: "STOPPING" },
    error: { tone: "red", text: "error", caption: "FAULT" },
    unknown: { tone: "red", text: "unknown", caption: "NO STATUS" },
    not_deployed: { tone: "grey", text: "not deployed", caption: "OFFLINE" },
    not_connected: { tone: "grey", text: "not connected", caption: "OFFLINE" },
};

// Receiving (data actually arriving) wins over the Swarm/connection state.
// While listening, a selected device that's up but silent is a fault ("no data").
export function deviceVisualState(device, listening) {
    const base = STATE_STYLES[device.state] ?? STATE_STYLES.unknown;
    const isUp = device.state === "running" || device.state === "connected";
    const lastSeen = device.last_seen_s == null ? "never" : `${device.last_seen_s}s ago`;
    const title = `${base.text} · last message ${lastSeen}`;

    if (device.receiving) {
        const rate = device.rate ? Math.round(device.rate) : null;
        return {
            tone: "green",
            text: rate ? `receiving · ${rate} msg/s` : "receiving",
            caption: rate ? `TX · ${rate}/s` : "TX",
            title,
        };
    }
    if (listening && isUp) {
        return { tone: "red", text: `${base.text} · no data`, caption: "NO DATA", title };
    }
    return { tone: base.tone, text: base.text, caption: base.caption, title };
}

export function deviceName(device) {
    return device.service ?? device.category;
}

// [[category, devices], ...] in CATEGORY_ORDER, unknown categories last
export function groupDevices(devices) {
    const groups = new Map();

    for (const device of devices) {
        if (!groups.has(device.category)) {
            groups.set(device.category, []);
        }
        groups.get(device.category).push(device);
    }

    const rank = (category) => {
        const i = CATEGORY_ORDER.indexOf(category);
        return i === -1 ? CATEGORY_ORDER.length : i;
    };

    return [...groups.entries()].sort(([a], [b]) => rank(a) - rank(b));
}
