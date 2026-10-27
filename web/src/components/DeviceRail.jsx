import { DeviceGraphic } from "./deviceGraphics";
import { CATEGORY_NAMES, TONE_COLORS, deviceName, deviceVisualState, groupDevices } from "../lib/deviceState";

const MODE_TEXT = { idle: "Idle", monitor: "Monitoring", record: "Recording", stopping: "Stopping" };
const TONE_ORDER = ["green", "blue", "red", "grey"];
const TONE_TEXT = { green: "sending", blue: "standby", red: "fault", grey: "offline" };

function DeviceTile({ device, state, dimmed, large }) {
    return (
        <div
            className={`dev-tile ${large ? "dev-tile-large" : ""} ${dimmed ? "dev-dim" : ""}`}
            data-tone={state.tone}
            style={{ "--tone": TONE_COLORS[state.tone] }}
            title={`${device.key} · ${state.title}`}
        >
            <div className="dev-tile-graphic">
                <DeviceGraphic category={device.category} />
            </div>
            <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-gray-900">
                    {deviceName(device)}
                </div>
                <div className="flex items-center gap-1.5 text-xs">
                    <span className="dev-led-dot"></span>
                    <span className="dev-caption truncate">{state.caption}</span>
                </div>
            </div>
        </div>
    );
}

// Left-gutter card with a graphic per device, colored by status:
// grey = offline, red = fault, blue = standby, green = sending data
export default function DeviceRail({ devices, selected, listening, captureMode }) {
    const states = new Map(
        devices.map((device) => [device.key, deviceVisualState(device, listening && selected.has(device.key))])
    );
    const counts = TONE_ORDER.map((tone) => [tone, [...states.values()].filter((s) => s.tone === tone).length]).filter(
        ([, n]) => n > 0
    );

    // Robot first as the large tile, then the edge devices
    const groups = groupDevices(devices).sort(([a], [b]) => (b === "robot") - (a === "robot"));

    return (
        <aside className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm" aria-label="Device status">
            <div className="mb-3 flex items-baseline justify-between gap-2 border-b border-gray-200 pb-3">
                <h2 className="text-base font-semibold text-gray-900">Field Devices</h2>
                <span className="text-xs text-gray-500">{MODE_TEXT[captureMode] ?? captureMode}</span>
            </div>

            {counts.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-x-3 gap-y-1 text-xs font-medium">
                    {counts.map(([tone, n]) => (
                        <span key={tone} style={{ color: TONE_COLORS[tone] }}>
                            {n} {TONE_TEXT[tone]}
                        </span>
                    ))}
                </div>
            )}

            {devices.length === 0 && (
                <p className="text-sm text-gray-500">No device data</p>
            )}

            <div className="flex flex-col gap-4">
                {groups.map(([category, group]) => (
                    <section key={category}>
                        <h3 className="mb-1.5 text-sm font-semibold text-gray-700">
                            {CATEGORY_NAMES[category] ?? category} · {group.length}
                        </h3>
                        <div className={`grid gap-2 ${category === "robot" ? "grid-cols-1" : "grid-cols-2"}`}>
                            {group.map((device) => (
                                <DeviceTile
                                    key={device.key}
                                    device={device}
                                    state={states.get(device.key)}
                                    dimmed={listening && !selected.has(device.key)}
                                    large={category === "robot"}
                                />
                            ))}
                        </div>
                    </section>
                ))}
            </div>
        </aside>
    );
}
