import os
import unittest
from unittest.mock import patch

from cupbot.cloud import load_cloud_config


PROFILE = "11111111-1111-4111-8111-111111111111"


class CloudConfigurationTests(unittest.TestCase):
    def test_unconfigured_account_identity_cannot_start(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                load_cloud_config()

    def test_config_requires_separate_identity_and_defaults_to_read_only(self):
        with patch.dict(os.environ, {"SIG_EXPECTED_PROFILE_ID": PROFILE}, clear=True):
            config, work, live = load_cloud_config()
        self.assertEqual(config["expected_profile_id"], PROFILE)
        self.assertEqual(work, "/var/data/sig-cup")
        self.assertFalse(live)

    def test_ephemeral_render_state_is_rejected_before_read_only_start(self):
        with patch.dict(os.environ, {"SIG_EXPECTED_PROFILE_ID": PROFILE, "RENDER": "true"}, clear=True):
            with patch("cupbot.autonomous.os.path.ismount", return_value=False):
                with self.assertRaises(RuntimeError):
                    load_cloud_config()
