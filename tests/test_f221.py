import io
import unittest

from fitelnet_ssh.application.run import Request, execute
from fitelnet_ssh.domain import Target, UsageError, validate_show_commands
from fitelnet_ssh.domain.redaction import validate_config_protocol
from fitelnet_ssh.infrastructure.session import open_session
from tests.fake_fitelnet import FakeFitelnet


def target(server, enable_password=None):
    return Target(
        name="test",
        host="127.0.0.1",
        username="admin",
        port=server.port,
        password="test-password",
        key_file=None,
        use_keys=False,
        ssh_config_file=None,
        enable_password=enable_password,
    )


class F221IntegrationTests(unittest.TestCase):
    def test_read_only_does_not_enter_config(self):
        with FakeFitelnet(hostname="") as server:
            session = open_session(target(server))
            try:
                self.assertIn("F221", session.show("show version"))
                self.assertIn("connected", session.show("show lte-module status"))
                self.assertNotIn("configure terminal", server.commands)
                self.assertNotIn("save moff", server.commands)
            finally:
                session.close()

    def test_edit_activate_persist_are_independent(self):
        with FakeFitelnet() as server:
            session = open_session(target(server))
            try:
                lines = ("hostname changed", "description test-secret")
                response = "\n".join(session.apply(lines))
                self.assertNotIn("test-secret", response)
                self.assertEqual(server.working, list(lines))
                self.assertEqual(server.running, [])
                self.assertEqual(server.startup, [])
                self.assertNotIn("changed#", session.show("show version"))
                session.commit()
                self.assertEqual(server.running, list(lines))
                self.assertEqual(server.startup, [])
                session.save()
                self.assertEqual(server.startup, list(lines))
            finally:
                session.close()

    def test_failure_stops_following_lines_commit_and_save(self):
        with FakeFitelnet() as server:
            server.responses["password hidden-value"] = "ERROR: rejected hidden-value"
            session = open_session(target(server))
            try:
                req = Request(
                    config_lines=(
                        "description before",
                        "password hidden-value",
                        "description after",
                    ),
                    commit=True,
                    save=True,
                )
                with self.assertRaises(UsageError) as caught:
                    execute(req, target(server), session, io.StringIO(), io.StringIO())
                self.assertNotIn("hidden-value", str(caught.exception))
                self.assertNotIn("description after", server.commands)
                self.assertNotIn("commit moff", server.commands)
                self.assertNotIn("save moff", server.commands)
            finally:
                session.close()

    def test_commit_rejection_stops_save(self):
        with FakeFitelnet() as server:
            server.responses["commit moff"] = (
                "Rollback-config is running.\r\nThis command cannot be executed."
            )
            session = open_session(target(server))
            try:
                with self.assertRaises(UsageError):
                    execute(
                        Request(commit=True, save=True),
                        target(server),
                        session,
                        io.StringIO(),
                        io.StringIO(),
                    )
                self.assertNotIn("save moff", server.commands)
            finally:
                session.close()

    def test_enable_password(self):
        with FakeFitelnet(user_mode=True) as server:
            session = open_session(target(server, "enable-secret"))
            try:
                self.assertIn("F221", session.show("show version"))
                self.assertIn("enable 15", server.commands)
                self.assertNotIn("enable-secret", server.commands)
            finally:
                session.close()


class ProtocolTests(unittest.TestCase):
    def test_terminal_injection_rejected_locally(self):
        for command in (
            "show version\nsave",
            "show version\t",
            "show x | save file",
            "show x;save",
        ):
            with self.subTest(command=command), self.assertRaises(UsageError):
                validate_show_commands((command,))
        for command in (
            "description x\nsave",
            "com moff",
            "save moff",
            "crypto key generate",
            "banner login",
        ):
            with self.subTest(command=command), self.assertRaises(UsageError):
                validate_config_protocol((command,))
