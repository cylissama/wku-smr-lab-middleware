import { useCallback, useEffect, useRef, useState } from "react";
import MessageWB from "./components/MessageWB";
import StatusIndicator from "./components/StatusIndicator";
import BackupCard from "./components/BackupCard";
import DashboardPanel from "./components/DashboardPanel";
import DeviceSelector from "./components/DeviceSelector";
import DeviceRail from "./components/DeviceRail";
import ContainerHealth from "./components/ContainerHealth";
import LogsPanel from "./components/LogsPanel";
import { HealthDetails, HealthStrip } from "./components/SystemHealth";
import { healthProblems } from "./lib/systemHealth";
import useSystemHealth from "./hooks/useSystemHealth";
import { reportDashboardError } from "./api/dashboardEvents";
import {
    getSessionLabels,
    getSessionStatus,
    getSessions,
    startSessionByLabel,
    stopSessionRequest,
} from "./api/sessionApi";
import { sendDashboardMessage } from "./api/messageApi";
import { getCapture, getDevices, startListening, stopListening } from "./api/captureApi";

const ROBOT_CAMERA_URL = import.meta.env.VITE_ROBOT_CAMERA_URL;
const DB_GUI_URL = import.meta.env.VITE_DB_GUI_URL;
const PORTAINER_URL = import.meta.env.VITE_PORTAINER_URL;
const DEFAULT_SESSION_LABEL_NAME = "Full System";

// Badge text/colors per capture mode (see fast_server/capture.py)
const CAPTURE_MODE_BADGES = {
    idle: { label: "Idle — not listening", className: "border-gray-300 bg-gray-100 text-gray-700", dot: "bg-gray-400" },
    monitor: { label: "Monitoring — not saved", className: "border-cyan-300 bg-cyan-50 text-cyan-800", dot: "bg-cyan-500 animate-pulse" },
    record: { label: "Recording", className: "border-green-300 bg-green-50 text-green-800", dot: "bg-green-500 animate-pulse" },
    stopping: { label: "Stopping — flushing data", className: "border-amber-300 bg-amber-50 text-amber-800", dot: "bg-amber-500 animate-pulse" },
};

function CaptureModeBadge({ mode }) {
    const badge = CAPTURE_MODE_BADGES[mode] ?? CAPTURE_MODE_BADGES.idle;

    return (
        <div className={`flex items-center gap-2 rounded-md border px-3 py-1 text-sm font-medium ${badge.className}`}>
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${badge.dot}`}></span>
            {badge.label}
        </div>
    );
}

function getErrorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}

// session.label is used as a raw URL path segment (see /session/start/{label},
// /imu/{label}, etc.), so it must never contain "/" or other characters that
// are unsafe in a path segment — collapse anything but alphanumerics/-/_ into
// a single underscore, regardless of what a session_label category is named.
function slugifyForLabel(value) {
    return value.replace(/[^a-zA-Z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
}

function getSessionDisplayValue(session) {
    if (!session || typeof session !== "object") {
        return "";
    }

    if (session.id !== undefined && session.id !== null) {
        return String(session.id);
    }

    if (session.label) {
        return String(session.label);
    }

    if (session.lable) {
        return String(session.lable);
    }

    return "";
}

export default function DataDashboard() {
    const [activeSession, setActiveSession] = useState(false);
    const [latestSession, setLatestSession] = useState("");
    const [isTestSession, setIsTestSession] = useState(true);
    const [isStopping, setIsStopping] = useState(false);
    const [isStatusLoading, setIsStatusLoading] = useState(true);
    const [isLatestSessionLoading, setIsLatestSessionLoading] = useState(true);
    const [dashboardError, setDashboardError] = useState("");
    const [isConfirmingSession, setIsConfirmingSession] = useState(false);
    const [isStartButtonShaking, setIsStartButtonShaking] = useState(false);
    const [sessionLabelOptions, setSessionLabelOptions] = useState([]);
    const [selectedSessionLabel, setSelectedSessionLabel] = useState("");
    const [isSessionLabelsLoading, setIsSessionLabelsLoading] = useState(true);
    const [captureMode, setCaptureMode] = useState("idle");
    const [isMonitorBusy, setIsMonitorBusy] = useState(false);
    // Device keys the backend is currently capturing (null = all), from /capture
    const [captureDevices, setCaptureDevices] = useState(null);
    const [devices, setDevices] = useState([]);
    const [selectedDevices, setSelectedDevices] = useState(new Set());
    const [devicesError, setDevicesError] = useState("");
    const [isDevicesLoading, setIsDevicesLoading] = useState(true);
    const hasInitialDeviceSelection = useRef(false);

    // fastapi-app's dependency report; session actions need the database
    const systemHealth = useSystemHealth(5000);
    const [isHealthExpanded, setIsHealthExpanded] = useState(false);
    // Container picked with "Show logs" in the Container Health box
    const [logsFocus, setLogsFocus] = useState(null);
    const clearLogsFocus = useCallback(() => setLogsFocus(null), []);
    const dbHealth = systemHealth.health?.components?.db;
    const dbUp = !systemHealth.apiError && dbHealth?.status === "ok";
    const dbUnavailableReason = systemHealth.apiError
        ? "The API is unreachable"
        : dbHealth?.status === "down"
          ? `Database unavailable: ${dbHealth.error}`
          : "Waiting for the database connection";
    const showHealthDetails = isHealthExpanded || healthProblems(systemHealth).length > 0;

    // Errors are also kept in the browser, so they're visible when the API
    // (which broadcasts them to the message boxes) is the thing that's down
    const sendMessage = async (dest, type, msg) => {
        if (type === "error") {
            reportDashboardError(msg);
        }
        try {
            await sendDashboardMessage(dest, type, msg);
        } catch (err) {
            console.error("sendMessage failed:", err);
        }
    };

    useEffect(() => {
        const getStatus = async () => {
            setIsStatusLoading(true);

            try {
                const json = await getSessionStatus();
                setActiveSession(Boolean(json.data));
                const capture = await getCapture();
                setCaptureMode(capture.mode);
                setCaptureDevices(capture.devices ?? null);
                setDashboardError("");
            } catch (e) {
                const message = `Unable to load session status: ${getErrorMessage(e)}`;
                setDashboardError(message);
                await sendMessage("camera", "error", message);
            } finally {
                setIsStatusLoading(false);
            }
        };

        getStatus();
    }, []);

    useEffect(() => {
    const pollStatus = async () => {
        try {
            const json = await getSessionStatus();
            setActiveSession(Boolean(json.data));
            const capture = await getCapture();
            setCaptureMode(capture.mode);
            setCaptureDevices(capture.devices ?? null);
        } catch (e) {
            // An unreachable API is already shown by the System Health strip;
            // anything else gets recorded with the dashboard's own errors
            if (!(e instanceof TypeError)) {
                reportDashboardError(`Session status poll failed: ${getErrorMessage(e)}`);
            }
        }
    };

    const intervalId = setInterval(pollStatus, 5000);

    return () => clearInterval(intervalId);
}, []);

    // (Re)loaded whenever the database (re)connects -- with it down there's
    // nothing to load, and the page must not wait on it
    useEffect(() => {
        if (!dbUp) {
            setIsLatestSessionLoading(false);
            return;
        }

        const getLatestSession = async () => {
            setIsLatestSessionLoading(true);

            try {
                const json = await getSessions();
                const sessions = Array.isArray(json.data) ? [...json.data] : [];

                if (sessions.length > 0) {
                    sessions.sort((a, b) => Number(b?.id ?? 0) - Number(a?.id ?? 0));
                    const newest = sessions[0];
                    setLatestSession(getSessionDisplayValue(newest));
                } else {
                    setLatestSession("");
                }
            } catch (e) {
                const message = `Unable to load latest session: ${getErrorMessage(e)}`;
                setDashboardError((current) => current || message);
                await sendMessage("camera", "error", message);
            } finally {
                setIsLatestSessionLoading(false);
            }
        };

        getLatestSession();
    }, [dbUp]);

    // Refresh device states every 3 s while monitoring/recording (so "receiving"
    // shows up quickly), every 10 s when idle
    useEffect(() => {
        const loadDevices = async () => {
            try {
                const json = await getDevices();

                if (json.success) {
                    const list = Array.isArray(json.data) ? json.data : [];
                    setDevices(list);
                    setDevicesError("");

                    // Start with everything selected; later refreshes only update states
                    if (!hasInitialDeviceSelection.current) {
                        setSelectedDevices(new Set(list.map((device) => device.key)));
                        hasInitialDeviceSelection.current = true;
                    }
                } else {
                    setDevicesError(`Unable to load devices: ${json.error}`);
                }
            } catch (e) {
                setDevicesError(`Unable to load devices: ${getErrorMessage(e)}`);
            } finally {
                setIsDevicesLoading(false);
            }
        };

        loadDevices();
        const intervalId = setInterval(loadDevices, captureMode === "idle" ? 10000 : 3000);

        return () => clearInterval(intervalId);
    }, [captureMode]);

    useEffect(() => {
        if (!dbUp) {
            setIsSessionLabelsLoading(false);
            return;
        }

        const loadSessionLabels = async () => {
            setIsSessionLabelsLoading(true);

            try {
                const json = await getSessionLabels();
                const labels = Array.isArray(json.data) ? json.data : [];
                setSessionLabelOptions(labels);

                const defaultLabel =
                    labels.find((option) => option.name === DEFAULT_SESSION_LABEL_NAME) ?? labels[0];

                if (defaultLabel) {
                    setSelectedSessionLabel(defaultLabel.name);
                }
            } catch (e) {
                const message = `Unable to load session labels: ${getErrorMessage(e)}`;
                setDashboardError((current) => current || message);
                await sendMessage("camera", "error", message);
            } finally {
                setIsSessionLabelsLoading(false);
            }
        };

        loadSessionLabels();
    }, [dbUp]);

    const allDeviceKeys = devices.map((device) => device.key);
    const selectedCount = allDeviceKeys.filter((key) => selectedDevices.has(key)).length;
    const isSelectionLocked = captureMode !== "idle" || activeSession;

    // What the picker shows: the live selection while locked, the draft otherwise
    const shownSelection = isSelectionLocked
        ? new Set(captureDevices ?? allDeviceKeys)
        : selectedDevices;

    // Device keys to send, or null for "every device" (also when the device list
    // couldn't be loaded, so the dashboard still works without stack-controller)
    const requestedDevices = () => {
        if (captureMode === "monitor") {
            return captureDevices; // recording keeps the monitored selection
        }
        if (devices.length === 0 || selectedCount === devices.length) {
            return null;
        }
        return allDeviceKeys.filter((key) => selectedDevices.has(key));
    };

    const hasDeviceSelection = devices.length === 0 || selectedCount > 0;

    const startSession = async () => {
        setDashboardError("");
        await sendMessage("misc", "info", "Starting new session...");

        try {
            const now = new Date();
            const label = `${slugifyForLabel(selectedSessionLabel)}_${now.toISOString()}`;
            const sessionDevices = requestedDevices();
            const data = await startSessionByLabel(label, isTestSession, selectedSessionLabel, sessionDevices);

            if (data.success) {
                setActiveSession(true);
                setCaptureMode("record");
                setCaptureDevices(sessionDevices);
                if (data.id !== undefined && data.id !== null) {
                    setLatestSession(String(data.id));
                }
                await sendMessage("misc", "info", "Session ready");
            } else {
                const message = "Failed to start session: " + data.error;
                setDashboardError(message);
                await sendMessage("misc", "error", message);
            }
        } catch (err) {
            const message = "An unexpected error has occurred: " + getErrorMessage(err);
            setDashboardError(message);
            await sendMessage("misc", "error", message);
        }
    };

    const handleStartSessionClick = async () => {
        if (!isConfirmingSession) {
            setIsConfirmingSession(true);
            setIsStartButtonShaking(true);
            return;
        }

        setIsConfirmingSession(false);
        await startSession();
    };

    const stopSession = async () => {
        setDashboardError("");
        await sendMessage("misc", "info", "Stopping the current session...");
        setIsStopping(true);

        try {
            const data = await stopSessionRequest();

            if (data.success) {
                await sendMessage("misc", "info", "Session stopped");
                setActiveSession(false);
                setCaptureMode("idle");
            } else {
                const message = "Failed to stop the session: " + data.error;
                setDashboardError(message);
                await sendMessage("misc", "error", message);
            }
        } catch (err) {
            const message = "An unexpected error has occurred: " + getErrorMessage(err);
            setDashboardError(message);
            await sendMessage("misc", "error", message);
        } finally {
            setIsStopping(false);
        }
    };

    const toggleMonitoring = async () => {
        setDashboardError("");
        setIsMonitorBusy(true);
        const starting = captureMode === "idle";

        try {
            const data = starting ? await startListening(requestedDevices()) : await stopListening();

            if (data.success) {
                setCaptureMode(data.mode);
                setCaptureDevices(data.devices ?? null);
            } else {
                const message = `Failed to ${starting ? "start" : "stop"} monitoring: ${data.error}`;
                setDashboardError(message);
                await sendMessage("misc", "error", message);
            }
        } catch (err) {
            const message = "An unexpected error has occurred: " + getErrorMessage(err);
            setDashboardError(message);
            await sendMessage("misc", "error", message);
        } finally {
            setIsMonitorBusy(false);
        }
    };

    useEffect(() => {
        if (activeSession) {
            setIsConfirmingSession(false);
            setIsStartButtonShaking(false);
        }
    }, [activeSession]);

    const isActionDisabled = isStatusLoading || isLatestSessionLoading || isSessionLabelsLoading;
    const canStartSession =
        dbUp && !activeSession && !isActionDisabled && !isMonitorBusy && hasDeviceSelection && Boolean(selectedSessionLabel);
    const isMonitoring = captureMode === "monitor";
    const canToggleMonitoring =
        !systemHealth.apiError &&
        !isActionDisabled &&
        !isMonitorBusy &&
        (isMonitoring || (captureMode === "idle" && !activeSession && hasDeviceSelection));

    return (
        // Wide screens get a 3-column grid: the device rail fills the left
        // gutter and the main column stays centered at its usual width
        <div className="min-h-screen bg-gray-100 text-gray-900 min-[1840px]:grid min-[1840px]:grid-cols-[1fr_minmax(0,80rem)_1fr]">
            <div className="hidden justify-self-end pt-20 min-[1840px]:block">
                <div className="sticky top-14 max-h-[calc(100vh-4.5rem)] w-64 overflow-y-auto">
                    <DeviceRail
                        devices={devices}
                        selected={shownSelection}
                        listening={captureMode === "monitor" || captureMode === "record"}
                        captureMode={captureMode}
                    />
                </div>
            </div>

            <div className="mx-auto w-full max-w-7xl px-4 pb-8 pt-20 sm:px-6 lg:px-8">
                <div className="sticky top-14 z-30 mb-6 rounded-xl border border-gray-200 bg-white/95 shadow-sm backdrop-blur">
                    <div className="flex flex-col gap-4 p-4 lg:p-5">
                        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                            <div className="flex flex-col gap-2">
                                <h1 className="text-xl font-semibold tracking-tight">
                                    Data Dashboard
                                </h1>
                                <div className="flex flex-wrap items-center gap-2">
                                    <StatusIndicator
                                        active={activeSession}
                                        onMsg="Session Active"
                                        offMsg={
                                            isStatusLoading
                                                ? "Checking Session..."
                                                : "Session Inactive"
                                        }
                                    />
                                    <CaptureModeBadge mode={captureMode} />
                                    <div className="rounded-md bg-gray-100 px-3 py-1 text-sm text-gray-700">
                                        Most Recent Session:{" "}
                                        {isLatestSessionLoading
                                            ? "Loading..."
                                            : latestSession || (dbUp ? "None" : "Unavailable")}
                                    </div>
                                </div>
                            </div>

                            <div className="flex flex-wrap items-center gap-2">
                                <select
                                    className="w-48 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 disabled:cursor-not-allowed disabled:bg-gray-100"
                                    value={selectedSessionLabel}
                                    onChange={(event) => setSelectedSessionLabel(event.target.value)}
                                    disabled={activeSession || isActionDisabled || !dbUp}
                                    title={dbUp ? undefined : dbUnavailableReason}
                                >
                                    {sessionLabelOptions.length === 0 && (
                                        <option value="">
                                            {isSessionLabelsLoading
                                            ? "Loading labels..."
                                            : dbUp
                                              ? "No labels available"
                                              : "Database unavailable"}
                                        </option>
                                    )}
                                    {sessionLabelOptions.map((option) => (
                                        <option key={option.id} value={option.name}>
                                            {option.name}
                                        </option>
                                    ))}
                                </select>

                                <button
                                    type="button"
                                    className={`w-40 rounded-md px-3 py-2 text-center text-sm font-semibold text-white shadow-sm transition disabled:cursor-not-allowed disabled:bg-gray-400 ${
                                        isMonitoring ? "bg-cyan-700 hover:bg-cyan-800" : "bg-cyan-600 hover:bg-cyan-700"
                                    }`}
                                    disabled={!canToggleMonitoring}
                                    onClick={toggleMonitoring}
                                    title="Run the devices and show live data without storing anything"
                                >
                                    {isMonitorBusy
                                        ? isMonitoring
                                            ? "Stopping..."
                                            : "Starting..."
                                        : isMonitoring
                                          ? "Stop Monitoring"
                                          : "Start Monitoring"}
                                </button>

                                <div className="relative">
                                    <button
                                        type="button"
                                        className={`w-40 rounded-md bg-green-600 px-3 py-2 text-center text-sm font-semibold text-white shadow-sm transition hover:bg-green-700 disabled:cursor-not-allowed disabled:bg-gray-400 ${
                                            isStartButtonShaking ? "animate-wiggle" : ""
                                        }`}
                                        disabled={!canStartSession}
                                        title={dbUp ? undefined : `Can't start a session: ${dbUnavailableReason}`}
                                        onClick={handleStartSessionClick}
                                        onAnimationEnd={() => setIsStartButtonShaking(false)}
                                    >
                                        {isStatusLoading
                                            ? "Loading..."
                                            : isConfirmingSession
                                              ? "Confirm & Start"
                                              : "Start Session"}
                                    </button>

                                    {isConfirmingSession && (
                                        <p className="absolute left-0 top-full z-10 mt-1 w-48 text-xs font-medium text-gray-600">
                                            Full test session? "Fake Data" Un-checked or just testing components? "Fake Data" Checked
                                        </p>
                                    )}
                                </div>

                                <button
                                    type="button"
                                    className="rounded-md bg-red-600 px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-red-700 disabled:cursor-not-allowed disabled:bg-gray-400"
                                    onClick={stopSession}
                                    disabled={!activeSession || isStopping || isActionDisabled}
                                >
                                    {isStopping ? "Stopping..." : "Stop Session"}
                                </button>

                                <label className="ml-1 inline-flex items-center gap-2 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700">
                                    <input
                                        type="checkbox"
                                        className="h-4 w-4 accent-green-600"
                                        checked={isTestSession}
                                        onChange={(event) => setIsTestSession(event.target.checked)}
                                        disabled={activeSession || isActionDisabled}
                                    />
                                    Fake Data
                                </label>
                            </div>
                        </div>

                        <div className="border-t border-gray-200 pt-4">
                            <div className="flex flex-wrap items-center gap-2">
                                <button
                                    type="button"
                                    className="rounded-md bg-yellow-500 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-yellow-600 disabled:cursor-not-allowed disabled:bg-gray-400"
                                    onClick={() => window.open(ROBOT_CAMERA_URL, "_blank")}
                                    disabled={!ROBOT_CAMERA_URL}
                                >
                                    Enclosure Safety Camera
                                </button>

                                <button
                                    type="button"
                                    className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-400"
                                    onClick={() => window.open(DB_GUI_URL, "_blank")}
                                    disabled={!DB_GUI_URL}
                                >
                                    pgAdmin
                                </button>

                                <button
                                    type="button"
                                    className="rounded-md bg-purple-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-purple-700 disabled:cursor-not-allowed disabled:bg-gray-400"
                                    onClick={() => window.open(PORTAINER_URL, "_blank")}
                                    disabled={!PORTAINER_URL}
                                >
                                    Portainer [WIP]
                                </button>
                            </div>
                        </div>

                        <div className="border-t border-gray-200 pt-3">
                            <HealthStrip
                                {...systemHealth}
                                expanded={showHealthDetails}
                                // Problems keep the details open, so no toggle then
                                onToggle={
                                    healthProblems(systemHealth).length > 0
                                        ? undefined
                                        : () => setIsHealthExpanded((open) => !open)
                                }
                            />
                        </div>
                    </div>
                </div>

                {showHealthDetails && <HealthDetails {...systemHealth} />}

                <div className="mb-6 rounded-xl border border-gray-200 bg-white p-4 shadow-sm lg:p-5">
                    <DeviceSelector
                        devices={devices}
                        selected={shownSelection}
                        onChange={setSelectedDevices}
                        locked={isSelectionLocked}
                        listening={captureMode === "monitor" || captureMode === "record"}
                        error={devicesError}
                        isLoading={isDevicesLoading}
                    />
                </div>

                {/* While the API is unreachable the System Health card already says so */}
                {dashboardError && !systemHealth.apiError && (
                    <div className="mb-6 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 shadow-sm">
                        {dashboardError}
                    </div>
                )}

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                    <DashboardPanel>
                        <MessageWB type="camera" />
                    </DashboardPanel>

                    <DashboardPanel>
                        <MessageWB type="imu" />
                    </DashboardPanel>

                    <DashboardPanel>
                        <MessageWB type="robot" />
                    </DashboardPanel>

                    <DashboardPanel>
                        <MessageWB type="misc" />
                    </DashboardPanel>

                    <DashboardPanel className="xl:col-span-2">
                        <BackupCard sendMessage={sendMessage} dbUp={dbUp} dbUnavailableReason={dbUnavailableReason} />
                    </DashboardPanel>
                </div>

                {/* Served by stack-controller through nginx, so both keep working while the API is down */}
                <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-5">
                    <DashboardPanel className="xl:col-span-2">
                        <ContainerHealth onShowLogs={setLogsFocus} />
                    </DashboardPanel>

                    <DashboardPanel className="xl:col-span-3">
                        <LogsPanel focusSource={logsFocus} onFocusHandled={clearLogsFocus} />
                    </DashboardPanel>
                </div>
            </div>
        </div>
    );
}
