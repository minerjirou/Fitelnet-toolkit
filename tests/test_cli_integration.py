import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.fake_fitelnet import FakeFitelnet


class CliIntegrationTests(unittest.TestCase):
    def test_backup_before_edit_and_requested_commit_save(self):
        with FakeFitelnet() as server, tempfile.TemporaryDirectory() as tmp:
            server.running = ["description previous"]
            backup = Path(tmp) / "before.conf"
            env = {k: v for k, v in os.environ.items() if not k.startswith("FITELNET_")}
            env["TEST_F221_PASSWORD"] = "test-password"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fitelnet_ssh",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(server.port),
                    "--user",
                    "admin",
                    "--no-ssh-config",
                    "--password-env",
                    "TEST_F221_PASSWORD",
                    "--backup",
                    str(backup),
                    "--config",
                    "description cli-secret",
                    "--commit",
                    "--save",
                ],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=40,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("previous", backup.read_text(encoding="utf-8"))
            self.assertNotIn("cli-secret", backup.read_text(encoding="utf-8"))
            self.assertEqual(server.running, ["description cli-secret"])
            self.assertEqual(server.startup, server.running)
            self.assertNotIn("cli-secret", result.stdout + result.stderr)
            self.assertLess(
                server.commands.index("show running.cfg"),
                server.commands.index("configure terminal"),
            )
            self.assertLess(
                server.commands.index("commit moff"), server.commands.index("save moff")
            )
