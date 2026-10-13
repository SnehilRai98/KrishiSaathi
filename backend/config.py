"""Small, optional settings read from environment variables (see .env.example)."""

import os


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


# Largest accepted leaf image, in megabytes.
MAX_UPLOAD_MB = _int_env("MAX_UPLOAD_MB", 10, 1, 50)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Upper sanity limit for a soil-test value (kg/ha). It only catches typos such as an extra zero
# and is not an agronomic threshold.
NPK_MAX_VALUE = _int_env("NPK_MAX_VALUE", 10000, 1, 1_000_000)

