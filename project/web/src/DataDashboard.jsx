import { useEffect, useState } from "react";
import MessageWB from "./components/MessageWB";
import StatusIndicator from "./components/StatusIndicator";
import BackupCard from "./components/BackupCard";
import DashboardPanel from "./components/DashboardPanel";
import {
    getSessionStatus,
    getSessions,
    startSessionByLabel,
    stopSessionRequest,
} from "./api/sessionApi";
import { sendDashboardMessage } from "./api/messageApi";

const ROBOT_CAMERA_URL = import.meta.env.VITE_ROBOT_CAMERA_URL;
const DB_GUI_URL = import.meta.env.VITE_DB_GUI_URL;
const PORTAINER_URL = import.meta.env.VITE_PORTAINER_URL;

function getErrorMessage(error) {
    return error instanceof Error ? error.message : String(error);
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

    const startSession = async () => {
        setDashboardError("");
        await sendMessage("misc", "info", "Starting new session...");

        try {
            const now = new Date();
            const label = "ses_" + now.toISOString();
            const data = await startSessionByLabel(label, isTestSession);

            if (data.success) {
                setActiveSession(true);
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

    const stopSession = async () => {
        setDashboardError("");
        await sendMessage("misc", "info", "Stopping the current session...");
        setIsStopping(true);

        try {
            const data = await stopSessionRequest();

            if (data.success) {
                await sendMessage("misc", "info", "Session stopped");
                setActiveSession(false);
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

    const isActionDisabled = isStatusLoading || isLatestSessionLoading;

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
                                    <div className="rounded-md bg-gray-100 px-3 py-1 text-sm text-gray-700">
                                        Most Recent Session:{" "}
                                        {isLatestSessionLoading
                                            ? "Loading..."
                                            : latestSession || "None"}
                                    </div>
                                </div>
                            </div>

                            <div className="flex flex-wrap items-center gap-2">
                                <button
                                    type="button"
                                    className="rounded-md bg-green-600 px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-green-700 disabled:cursor-not-allowed disabled:bg-gray-400"
                                    disabled={activeSession || isActionDisabled}
                                    onClick={startSession}
                                >
                                    {isStatusLoading ? "Loading..." : "Start Session"}
                                </button>

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
                                    Test Session
                                </label>
                            </div>
                        </div>

                        <div className="border-t border-gray-200 pt-4">
                            <div className="flex flex-wrap items-center gap-2">
                                <button
                                    type="button"
                                    className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-400"
                                >
                                    Clear Cache [PLHDR]
                                </button>

                                <button
                                    type="button"
                                    className="rounded-md bg-yellow-500 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-yellow-600 disabled:cursor-not-allowed disabled:bg-gray-400"
                                    onClick={() => window.open(ROBOT_CAMERA_URL, "_blank")}
                                    disabled={!ROBOT_CAMERA_URL}
                                >
                                    Open Robot Camera
                                </button>

                                <button
                                    type="button"
                                    className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-400"
                                    onClick={() => window.open(DB_GUI_URL, "_blank")}
                                    disabled={!DB_GUI_URL}
                                >
                                    Open Database GUI
                                </button>

                                <button
                                    type="button"
                                    className="rounded-md bg-purple-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-purple-700 disabled:cursor-not-allowed disabled:bg-gray-400"
                                    onClick={() => window.open(PORTAINER_URL, "_blank")}
                                    disabled={!PORTAINER_URL}
                                >
                                    Open Portainer
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
