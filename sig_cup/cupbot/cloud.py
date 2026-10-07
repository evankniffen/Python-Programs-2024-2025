"""Render entry point. Credentials enter through SIG_API_KEY only."""

import os
from pathlib import Path
import uuid

from .api import API
from .autonomous import run_worker, verify_state_disk
from .bootstrap import restore_state
from .runtime import read_json


def load_cloud_config():
    root = Path(__file__).resolve().parent.parent
    config = read_json(os.environ.get("SIG_CONFIG_PATH", str(root / "config.autonomous.json")))
    profile = os.environ.get("SIG_EXPECTED_PROFILE_ID", "")
    if not profile or uuid.UUID(profile).int == 0:
        raise ValueError("Set SIG_EXPECTED_PROFILE_ID to the intended participant account.")
    config["expected_profile_id"] = profile
    mode = os.environ.get("SIG_LIVE", "false").lower()
    if mode not in ("true", "false"):
        raise ValueError("SIG_LIVE must be true or false.")
    work = os.environ.get("SIG_STATE_DIR", "/var/data/sig-cup")
    verify_state_disk(work)
    return config, work, mode == "true"


def main():
    config, work, live = load_cloud_config()
    restored = restore_state(os.environ.get("SIG_STATE_BOOTSTRAP_B64", ""), work,
                             config["expected_profile_id"])
    print(restored, flush=True)
    return run_worker(API(config["api_base"]), config, work, live=live)


if __name__ == "__main__":
    main()
