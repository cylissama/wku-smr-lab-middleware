import { useEffect, useRef } from "react";

const CATEGORY_ORDER = ["imu", "camera", "robot"];
const CATEGORY_NAMES = { imu: "IMU", camera: "Camera", robot: "Robot" };

// Device state (from GET /devices) -> dot color and text
const STATE_STYLES = {
    running: { dot: "bg-green-500", text: "running" },
    connected: { dot: "bg-green-500", text: "connected" },
    deploying: { dot: "bg-amber-400", text: "starting" },
    removing: { dot: "bg-amber-400", text: "stopping" },
    error: { dot: "bg-red-500", text: "error" },
    not_deployed: { dot: "bg-gray-300", text: "not deployed" },
    not_connected: { dot: "bg-gray-300", text: "not connected" },
    unknown: { dot: "bg-gray-300", text: "unknown" },
};

// Checkbox that can also show "some selected"
function TriStateCheckbox({ checked, indeterminate, disabled, onChange, label }) {
    const ref = useRef(null);

    useEffect(() => {
        if (ref.current) {
            ref.current.indeterminate = indeterminate;
        }
    }, [indeterminate]);

    return (
        <input
            ref={ref}
            type="checkbox"
            className="h-4 w-4 accent-blue-600 disabled:cursor-not-allowed"
            checked={checked}
            disabled={disabled}
            onChange={onChange}
            aria-label={label}
        />
    );
}

// Receiving (data actually arriving) wins over the Swarm/connection state.
// While listening, a device that's up but silent is flagged as "no data".
function deviceStatus(device, listening) {
    const base = STATE_STYLES[device.state] ?? STATE_STYLES.unknown;
    const isUp = device.state === "running" || device.state === "connected";
    const lastSeen = device.last_seen_s == null ? "never" : `${device.last_seen_s}s ago`;
    const title = `${base.text} · last message ${lastSeen}`;

    if (device.receiving) {
        return {
            dot: "bg-cyan-500 animate-pulse",
            text: device.rate ? `receiving · ${Math.round(device.rate)} msg/s` : "receiving",
            title,
        };
    }
    if (listening && isUp) {
        return { dot: "bg-amber-400", text: `${base.text} · no data`, title };
    }
    return { ...base, title };
}

function deviceName(device) {
    return device.service ?? device.category;
}

function groupDevices(devices) {
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

// Picks which devices to monitor/record: all, a category, or single devices.
// selected is a Set of device keys; locked while monitoring or recording.
export default function DeviceSelector({ devices, selected, onChange, locked, listening, error, isLoading }) {
    const allKeys = devices.map((device) => device.key);
    const selectedCount = allKeys.filter((key) => selected.has(key)).length;

    const setKeys = (keys, on) => {
        const next = new Set(selected);
        for (const key of keys) {
            if (on) {
                next.add(key);
            } else {
                next.delete(key);
            }
        }
        onChange(next);
    };

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-4">
                    <h2 className="text-base font-semibold text-gray-900">Devices</h2>
                    <label className="inline-flex items-center gap-2 text-sm text-gray-700">
                        <TriStateCheckbox
                            checked={devices.length > 0 && selectedCount === devices.length}
                            indeterminate={selectedCount > 0 && selectedCount < devices.length}
                            disabled={locked || devices.length === 0}
                            onChange={(event) => setKeys(allKeys, event.target.checked)}
                            label="All devices"
                        />
                        All devices ({selectedCount} of {devices.length} selected)
                    </label>
                </div>
                <p className="text-xs text-gray-500">
                    {locked
                        ? "Selection is locked while monitoring or recording."
                        : "Only the selected devices are started, shown, and recorded."}
                </p>
            </div>

            {error && (
                <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
                    {error}
                </div>
            )}

            {devices.length === 0 && !error && (
                <p className="text-sm text-gray-500">{isLoading ? "Loading devices..." : "No devices found."}</p>
            )}

            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                {groupDevices(devices).map(([category, group]) => {
                    const keys = group.map((device) => device.key);
                    const groupSelected = keys.filter((key) => selected.has(key)).length;

                    return (
                        <div key={category} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                            <label className="mb-2 flex items-center justify-between gap-2">
                                <span className="inline-flex items-center gap-2 text-sm font-semibold text-gray-900">
                                    <TriStateCheckbox
                                        checked={groupSelected === group.length}
                                        indeterminate={groupSelected > 0 && groupSelected < group.length}
                                        disabled={locked}
                                        onChange={(event) => setKeys(keys, event.target.checked)}
                                        label={`All ${CATEGORY_NAMES[category] ?? category} devices`}
                                    />
                                    {CATEGORY_NAMES[category] ?? category}
                                </span>
                                <span className="text-xs text-gray-500">
                                    {groupSelected}/{group.length}
                                </span>
                            </label>

                            <ul className="flex flex-col gap-1.5">
                                {group.map((device) => {
                                    const style = deviceStatus(device, listening && selected.has(device.key));

                                    return (
                                        <li key={device.key}>
                                            <label className="flex items-center justify-between gap-2 rounded px-2 py-1 text-sm hover:bg-white">
                                                <span className="inline-flex items-center gap-2 text-gray-800">
                                                    <input
                                                        type="checkbox"
                                                        className="h-4 w-4 accent-blue-600 disabled:cursor-not-allowed"
                                                        checked={selected.has(device.key)}
                                                        disabled={locked}
                                                        onChange={(event) => setKeys([device.key], event.target.checked)}
                                                    />
                                                    {deviceName(device)}
                                                    <span className="text-xs text-gray-400">{device.key}</span>
                                                </span>
                                                <span
                                                    className="inline-flex items-center gap-1.5 text-xs text-gray-600"
                                                    title={style.title}
                                                >
                                                    <span className={`inline-block h-2 w-2 rounded-full ${style.dot}`}></span>
                                                    {style.text}
                                                </span>
                                            </label>
                                        </li>
                                    );
                                })}
                            </ul>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
