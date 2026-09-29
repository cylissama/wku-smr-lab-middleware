const API_URL = import.meta.env.VITE_API_URL;
const WS_URL = import.meta.env.VITE_WS_URL;

async function handleResponse(response) {
    if (!response.ok) {
        let errorMessage = `API request failed with status ${response.status}`;

        try {
            const errorData = await response.json();
            if (errorData?.error) {
                errorMessage = errorData.error;
            }
        } catch {
            // Ignore JSON parsing errors and keep default message
        }

        throw new Error(errorMessage);
    }

    return response.json();
}

function resolveApiUrl(path) {
    if (/^https?:\/\//i.test(path)) {
        return path;
    }

    if (!API_URL) {
        throw new Error("VITE_API_URL is not configured.");
    }

    return `${API_URL.replace(/\/+$/, "")}/${String(path).replace(/^\/+/, "")}`;
}

export function getApiBaseUrl() {
    return API_URL || "";
}

export function getWsBaseUrl() {
    if (WS_URL) {
        return WS_URL;
    }

    if (!API_URL) {
        return "";
    }

    return API_URL.replace(/^http/i, "ws");
}

export function resolveWsUrl(path) {
    if (/^wss?:\/\//i.test(path)) {
        return path;
    }

    const baseUrl = getWsBaseUrl();

    if (!baseUrl) {
        throw new Error("VITE_WS_URL and VITE_API_URL are not configured.");
    }

    return `${baseUrl.replace(/\/+$/, "")}/${String(path).replace(/^\/+/, "")}`;
}

export async function apiRequest(path, options = {}) {
    const { method = "GET", body } = options;

    const requestOptions = {
        method,
        headers: {},
    };

    if (body !== undefined) {
        requestOptions.headers["Content-Type"] = "application/json";
        requestOptions.body = typeof body === "string" ? body : JSON.stringify(body);
    }

    const response = await fetch(resolveApiUrl(path), requestOptions);

    return handleResponse(response);
}

export async function apiGet(path) {
    return apiRequest(path, { method: "GET" });
}

export async function apiPost(path, body) {
    return apiRequest(path, { method: "POST", body });
}
