"""Lightweight .env loader for local development."""
import os
from pathlib import Path


def load_local_env() -> None:
    """Load key=value pairs from the repo root .env without overriding existing env vars."""
    current_file = Path(__file__).resolve()
    env_path = current_file.parent.parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key or key in os.environ:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ[key] = value
