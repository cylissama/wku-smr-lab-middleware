import { useEffect, useRef, useState } from "react";
import { describeApiError, getHealth } from "../api/healthApi";
import { reportDashboardEvent } from "../api/dashboardEvents";

// Polls GET /health. While the API is unreachable, the last report is kept
// (marked stale by apiError) and the outage is recorded once in the
// dashboard's local event list.
export default function useSystemHealth(intervalMs = 5000) {
    const [state, setState] = useState({ health: null, apiError: null, lastContact: null, loading: true });
    const wasUnreachable = useRef(false);

    useEffect(() => {
        let cancelled = false;

        const poll = async () => {
            try {
                const health = await getHealth();
                if (cancelled) return;

                if (wasUnreachable.current) {
                    reportDashboardEvent("API reachable again", 20, "health");
                    wasUnreachable.current = false;
                }
                setState({ health, apiError: null, lastContact: Date.now(), loading: false });
            } catch (err) {
                if (cancelled) return;

                const apiError = describeApiError(err);
                if (!wasUnreachable.current) {
                    reportDashboardEvent(apiError, 40, "health");
                    wasUnreachable.current = true;
                }
                setState((prev) => ({ ...prev, apiError, loading: false }));
            }
        };

        poll();
        const intervalId = setInterval(poll, intervalMs);

        return () => {
            cancelled = true;
            clearInterval(intervalId);
        };
    }, [intervalMs]);

    return state;
}

// Re-renders every intervalMs so "updated 3s ago" style text stays current
export function useNow(intervalMs = 1000) {
    const [now, setNow] = useState(() => Date.now());

    useEffect(() => {
        const intervalId = setInterval(() => setNow(Date.now()), intervalMs);
        return () => clearInterval(intervalId);
    }, [intervalMs]);

    return now;
}
