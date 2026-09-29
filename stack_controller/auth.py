import os

from fastapi import Header, HTTPException, status


def verify_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("STACK_CONTROLLER_TOKEN")

    if not expected:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "STACK_CONTROLLER_TOKEN is not configured on the agent",
        )

    if authorization != f"Bearer {expected}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing bearer token")
