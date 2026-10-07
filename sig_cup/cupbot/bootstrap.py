"""Import the private order journal once, without overwriting newer cloud state."""

import base64
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile


DATABASES = ("basket_operations.sqlite3", "operations.sqlite3", "worker.sqlite3")


def restore_state(encoded, destination, expected_profile_id):
    destination = Path(destination)
    present = [name for name in DATABASES if (destination / name).exists()]
    if present:
        if len(present) != len(DATABASES):
            raise ValueError("Incomplete existing journal; operator review is required.")
        return "existing_state_preserved"
    if not encoded:
        raise ValueError("Set SIG_STATE_BOOTSTRAP_B64 for the first cloud startup.")
    if len(encoded) > 7_000_000:
        raise ValueError("State bootstrap exceeds its size limit.")
    raw = base64.b64decode(encoded, validate=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".sig-state-", dir=destination.parent))
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            allowed = set(DATABASES) | {"STOP", "RESTORE.txt"}
            if len(names) != len(set(names)) or set(names) - allowed or not set(DATABASES) <= set(names):
                raise ValueError("Unexpected state archive members.")
            if sum(info.file_size for info in archive.infolist()) > 5_000_000:
                raise ValueError("Expanded state bootstrap exceeds its size limit.")
            for name in DATABASES:
                path = staging / name
                path.write_bytes(archive.read(name))
                path.chmod(0o600)
                db = sqlite3.connect(path)
                try:
                    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise ValueError("Invalid journal database.")
                    if name == "worker.sqlite3":
                        profile = db.execute("SELECT value FROM metadata WHERE key='profile_id'").fetchone()
                        if profile is None or json.loads(profile[0]) != expected_profile_id:
                            raise ValueError("State archive belongs to another participant.")
                finally:
                    db.close()
        # Only a wholly empty target may be replaced. A restart never overwrites
        # an existing journal, even if the bootstrap environment value remains.
        if destination.exists():
            destination.rmdir()
        os.replace(staging, destination)
        return "private_journal_restored"
    finally:
        if staging.exists():
            shutil.rmtree(staging)
