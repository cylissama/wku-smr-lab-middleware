# Docker HEALTHCHECK for fastapi-app (docker-compose.yml): healthy as long as
# the API answers /health. Dependencies being down does NOT make it unhealthy --
# restarting the API can't fix the NAS -- but they're printed, so Docker's
# health log (docker inspect, the dashboard's Container Health box) says why
# the system is degraded.
#
#   python -m fast_server.healthcheck                     (fastapi-app)
#   python -m fast_server.healthcheck http://127.0.0.1:8090/queue/status   (tcp)

import json
import sys
import urllib.request

URL = "http://127.0.0.1:8000/health"


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else URL
    try:
        with urllib.request.urlopen(url, timeout=4) as resp:
            data = json.load(resp)
    except Exception as e:
        print(f"not answering {url}: {type(e).__name__}: {e}")
        return 1

    # tcp's /queue/status reports only its own DB connection
    if "components" not in data:
        db = data.get("db") or {}
        print(f"alive; db {db.get('status', 'unknown')}" + (f" ({db.get('error')})" if db.get("error") else ""))
        return 0

    down = [
        f"{name} down {int(c.get('for_s') or 0)}s ({c.get('error')})"
        for name, c in data.get("components", {}).items()
        if c.get("status") == "down"
    ]
    print(f"alive; {data.get('overall')}" + (f"; {'; '.join(down)}" if down else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
