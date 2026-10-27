import { useState } from "react";
import { CATEGORY_NAMES } from "../lib/deviceState";

const CHANGED_COLOR = "#0891b2";
const DEFAULT_COLOR = "#9ca3af";

function formatValue(param, value) {
    if (value === null || value === undefined) {
        return "—";
    }
    if (param.type === "bool") {
        return value ? "On" : "Off";
    }
    return `${value}${param.unit ? ` ${param.unit}` : ""}`;
}

function ParamTile({ param, draft, onDraft, locked, error }) {
    const edited = param.key in draft;
    // A draft of null means "reset", so show the default it goes back to
    const value = edited ? (draft[param.key] ?? param.default) : param.value;
    const changed = edited || param.overridden;
    const inputId = `param-${param.key}`;

    return (
        <div className="dev-tile" style={{ "--tone": error ? "#ef4444" : changed ? CHANGED_COLOR : DEFAULT_COLOR }}>
            <div className="flex items-baseline justify-between gap-2">
                <label
                    htmlFor={inputId}
                    className="truncate text-sm font-semibold text-gray-900"
                    title={`${param.key} · ${param.help ?? ""}`}
                >
                    {param.label}
                </label>
                {changed && !locked && (
                    <span className="text-xs font-medium text-cyan-700">{edited ? "Edited" : "Changed"}</span>
                )}
            </div>

            {locked ? (
                <div className="text-sm text-gray-800">{formatValue(param, param.value)}</div>
            ) : param.type === "bool" ? (
                <label className="inline-flex items-center gap-2 text-sm text-gray-700">
                    <input
                        id={inputId}
                        type="checkbox"
                        className="h-4 w-4 accent-blue-600"
                        checked={Boolean(value)}
                        onChange={(event) => onDraft(param.key, event.target.checked)}
                    />
                    {value ? "On" : "Off"}
                </label>
            ) : (
                <div className="flex items-center gap-1.5">
                    <input
                        id={inputId}
                        type="number"
                        inputMode="decimal"
                        min={param.min}
                        max={param.max}
                        step={param.type === "int" ? 1 : "any"}
                        className="w-24 rounded-md border border-gray-200 bg-white px-2 py-1 text-sm text-gray-900 focus:border-blue-500 focus:outline-none"
                        value={value ?? ""}
                        onChange={(event) => onDraft(param.key, event.target.value)}
                    />
                    <span className="text-xs text-gray-500">{param.unit}</span>
                </div>
            )}

            <div className="text-xs text-gray-500">
                default {formatValue(param, param.default)}
                {param.type !== "bool" && ` · ${param.min}–${param.max}`}
                {!locked && param.overridden && !edited && (
                    <button
                        type="button"
                        className="ml-2 text-blue-600 underline hover:text-blue-800"
                        onClick={() => onDraft(param.key, null)}
                    >
                        reset
                    </button>
                )}
            </div>
            {error && <div className="text-xs text-red-600">{error}</div>}
        </div>
    );
}

// Run parameters card (GET /parameters), edited as a draft and sent in one PUT
// on Apply. Locked while a session is recording.
export default function ParamRail({ params, editable, captureMode, loadError, onSave }) {
    const [draft, setDraft] = useState({});
    const [errors, setErrors] = useState({});
    const [saveError, setSaveError] = useState("");
    const [isSaving, setIsSaving] = useState(false);

    const locked = !editable;
    const hasDraft = Object.keys(draft).length > 0;
    const groups = [...new Set((params ?? []).map((p) => p.group))].map((group) => [
        group,
        params.filter((p) => p.group === group),
    ]);

    const setDraftValue = (key, value) => setDraft((current) => ({ ...current, [key]: value }));

    const apply = async () => {
        setIsSaving(true);
        setSaveError("");
        try {
            const data = await onSave(draft);
            if (data.success) {
                setDraft({});
                setErrors({});
            } else {
                setErrors(data.errors ?? {});
                setSaveError(data.errors ? "" : data.error);
            }
        } catch (err) {
            setSaveError(err instanceof Error ? err.message : String(err));
        } finally {
            setIsSaving(false);
        }
    };

    const discard = () => {
        setDraft({});
        setErrors({});
        setSaveError("");
    };

    return (
        <aside className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm" aria-label="Run parameters">
            <div className="mb-3 flex items-baseline justify-between gap-2 border-b border-gray-200 pb-3">
                <h2 className="text-base font-semibold text-gray-900">Run Parameters</h2>
                <span className="text-xs text-gray-500">{locked ? "Locked" : "Editable"}</span>
            </div>

            {locked && (
                <p className="mb-3 text-xs text-amber-700">In use by the running session. Editable once it stops.</p>
            )}
            {loadError && (
                <div className="mb-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
                    {loadError}
                </div>
            )}
            {!params && !loadError && <p className="text-sm text-gray-500">Loading...</p>}

            <div className="flex flex-col gap-4">
                {groups.map(([group, list]) => (
                    <section key={group}>
                        <h3 className="mb-1.5 text-sm font-semibold text-gray-700">{CATEGORY_NAMES[group] ?? group}</h3>
                        <div className="flex flex-col gap-2">
                            {list.map((param) => (
                                <ParamTile
                                    key={param.key}
                                    param={param}
                                    draft={draft}
                                    onDraft={setDraftValue}
                                    locked={locked}
                                    error={errors[param.key]}
                                />
                            ))}
                        </div>
                    </section>
                ))}
            </div>

            {!locked && hasDraft && (
                <div className="mt-4 flex flex-col gap-2">
                    {captureMode === "monitor" && (
                        <p className="text-xs text-amber-700">Applying restarts the affected devices.</p>
                    )}
                    <div className="flex gap-2">
                        <button
                            type="button"
                            className="flex-1 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                            onClick={discard}
                            disabled={isSaving}
                        >
                            Discard
                        </button>
                        <button
                            type="button"
                            className="flex-1 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-400"
                            onClick={apply}
                            disabled={isSaving}
                        >
                            {isSaving ? "Applying..." : "Apply"}
                        </button>
                    </div>
                </div>
            )}
            {saveError && <p className="mt-2 text-sm text-red-600">{saveError}</p>}
        </aside>
    );
}
