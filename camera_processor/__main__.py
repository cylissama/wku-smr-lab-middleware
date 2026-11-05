import logging
import sys

from common.log_schema import JsonLineFormatter

from . import service


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "healthcheck":
        return service.healthcheck()

    # One JSON LogRecord per line on stdout, like every AMS service, so the
    # dashboard's Logs box (stack-controller GET /logs) reads them as-is.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLineFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)

    service.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
