import { useEffect, useState } from "react";
import MessageWB from "./components/MessageWB";
import StatusIndicator from "./components/StatusIndicator";
import BackupCard from "./components/BackupCard";
import DashboardPanel from "./components/DashboardPanel";
import {
    getSessionLabels,
    getSessionStatus,
    getSessions,
    startSessionByLabel,
    stopSessionRequest,
} from "./api/sessionApi";
import { sendDashboardMessage } from "./api/messageApi";
import { getCapture, startListening, stopListening } from "./api/captureApi";

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

    const sendMessage = async (dest, type, msg) => {
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
        } catch {
            // stay quiet on poll failures — the initial load effect already surfaces errors
        }
    };

    const intervalId = setInterval(pollStatus, 5000);

    return () => clearInterval(intervalId);
}, []);

    useEffect(() => {
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
    }, []);

    useEffect(() => {
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
    }, []);

    const startSession = async () => {
        setDashboardError("");
        await sendMessage("misc", "info", "Starting new session...");

        try {
            const now = new Date();
            const label = `${slugifyForLabel(selectedSessionLabel)}_${now.toISOString()}`;
            const data = await startSessionByLabel(label, isTestSession, selectedSessionLabel);

            if (data.success) {
                setActiveSession(true);
                setCaptureMode("record");
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
            const data = starting ? await startListening() : await stopListening();

            if (data.success) {
                setCaptureMode(data.mode);
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
        !activeSession && !isActionDisabled && !isMonitorBusy && Boolean(selectedSessionLabel);
    const isMonitoring = captureMode === "monitor";
    const canToggleMonitoring =
        !isActionDisabled && !isMonitorBusy && (isMonitoring || (captureMode === "idle" && !activeSession));

    return (
        <div className="min-h-screen bg-gray-100 text-gray-900">
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
                                            : latestSession || "None"}
                                    </div>
                                </div>
                            </div>

                            <div className="flex flex-wrap items-center gap-2">
                                <select
                                    className="w-48 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 disabled:cursor-not-allowed disabled:bg-gray-100"
                                    value={selectedSessionLabel}
                                    onChange={(event) => setSelectedSessionLabel(event.target.value)}
                                    disabled={activeSession || isActionDisabled}
                                >
                                    {sessionLabelOptions.length === 0 && (
                                        <option value="">
                                            {isSessionLabelsLoading ? "Loading labels..." : "No labels available"}
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
                                    className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-400"
                                >
                                    Clear Cache [WIP]
                                </button>

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
                    </div>
                </div>

                {dashboardError && (
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
                        <BackupCard sendMessage={sendMessage} />
                    </DashboardPanel>
                </div>
            </div>
        </div>
    );
}
