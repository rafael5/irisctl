"""Profile / config loading.

Resolution order (lowest to highest precedence):
1. Built-in defaults (foia / 127.0.0.1 / 52773 / 1972).
2. ~/.config/irisctl/config.toml — `[profiles.<name>]` table.
3. IRISCTL_* environment variables.
4. CLI flags (passed to load_profile via the `profile=` argument).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "irisctl" / "config.toml"


@dataclass
class Profile:
    container: str
    host: str
    web_port: int
    superserver_port: int
    data_dir: Path
    rpc_port: int = 9430
    vistalink_port: int = 8001
    auth_user: str | None = None
    auth_pw_env: str | None = None

    def web_base_url(self) -> str:
        return f"http://{self.host}:{self.web_port}"

    def messages_log_path(self) -> Path:
        return self.data_dir / "mgr" / "messages.log"


_DEFAULTS: dict[str, object] = {
    "container": "foia",
    "host": "127.0.0.1",
    "web_port": 52773,
    "superserver_port": 1972,
    "rpc_port": 9430,
    "vistalink_port": 8001,
    "data_dir": str(Path.home() / "data" / "foia-iris"),
}


def load_profile(
    profile: str | None = None,
    *,
    config_path: Path | None = None,
) -> Profile:
    cfg_path = config_path or DEFAULT_CONFIG_PATH
    file_data = _load_file(cfg_path)

    profile_name = (
        profile
        or os.environ.get("IRISCTL_PROFILE")
        or file_data.get("default_profile")
    )
    profiles_section = file_data.get("profiles", {}) or {}
    if profile_name and profile_name in profiles_section:
        merged = {**_DEFAULTS, **profiles_section[profile_name]}
    elif profile_name and profile_name not in profiles_section and profile:
        # Explicit --profile that doesn't exist is an error.
        raise KeyError(f"profile {profile_name!r} not found in {cfg_path}")
    else:
        merged = dict(_DEFAULTS)

    # Env overrides
    if v := os.environ.get("IRISCTL_CONTAINER"):
        merged["container"] = v
    if v := os.environ.get("IRISCTL_HOST"):
        merged["host"] = v
    if v := os.environ.get("IRISCTL_WEB_PORT"):
        merged["web_port"] = int(v)
    if v := os.environ.get("IRISCTL_SUPERSERVER_PORT"):
        merged["superserver_port"] = int(v)
    if v := os.environ.get("IRISCTL_DATA_DIR"):
        merged["data_dir"] = v

    return Profile(
        container=str(merged["container"]),
        host=str(merged["host"]),
        web_port=int(merged["web_port"]),
        superserver_port=int(merged["superserver_port"]),
        rpc_port=int(merged.get("rpc_port", 9430)),
        vistalink_port=int(merged.get("vistalink_port", 8001)),
        data_dir=Path(str(merged["data_dir"])).expanduser(),
        auth_user=merged.get("auth_user"),
        auth_pw_env=merged.get("auth_pw_env"),
    )


def _load_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)
