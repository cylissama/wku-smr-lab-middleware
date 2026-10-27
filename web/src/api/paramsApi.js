import { apiGet, apiRequest } from "./apiClient";

// Run parameters: [{ key, label, group, type, min, max, unit, help, default,
// value, overridden }], plus whether they can be changed right now (editable)
export async function getParameters() {
    return apiGet("/parameters");
}

// values: { KEY: value }, null resets that parameter to its default
export async function saveParameters(values) {
    return apiRequest("/parameters", { method: "PUT", body: { values } });
}
