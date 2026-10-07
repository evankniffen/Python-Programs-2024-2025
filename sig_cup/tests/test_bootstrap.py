import base64
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from cupbot.bootstrap import DATABASES, restore_state


PROFILE = "11111111-1111-4111-8111-111111111111"


def snapshot(root, profile=PROFILE, extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in DATABASES:
            path = root / name
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("INSERT INTO metadata VALUES (?, ?)", ("profile_id", json.dumps(profile)))
            db.commit()
            db.close()
            archive.write(path, name)
        if extra:
            archive.writestr(extra, "unexpected")
    return base64.b64encode(stream.getvalue()).decode()


class StateImportTests(unittest.TestCase):
    def test_restore_once_preserves_newer_state_on_redeployment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            encoded = snapshot(root)
            target = root / "cloud"
            self.assertEqual(restore_state(encoded, target, PROFILE), "private_journal_restored")
            path = target / "operations.sqlite3"
            db = sqlite3.connect(path)
            db.execute("INSERT INTO metadata VALUES ('new_cloud_record', 'retained')")
            db.commit()
            db.close()
            self.assertEqual(restore_state(encoded, target, PROFILE), "existing_state_preserved")
            db = sqlite3.connect(path)
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='new_cloud_record'").fetchone(), ("retained",))
            db.close()

    def test_wrong_participant_cannot_install_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                restore_state(snapshot(root), root / "cloud", "other-participant")
            self.assertFalse((root / "cloud").exists())

    def test_partial_existing_state_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / DATABASES[0]).write_bytes(b"existing")
            with self.assertRaises(ValueError):
                restore_state("unused", root, PROFILE)
            self.assertEqual((root / DATABASES[0]).read_bytes(), b"existing")

    def test_unexpected_archive_paths_cannot_be_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                restore_state(snapshot(root, extra="../outside"), root / "cloud", PROFILE)
            self.assertFalse((root / "cloud").exists())

    def test_first_start_requires_the_private_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                restore_state("", Path(directory) / "cloud", PROFILE)
