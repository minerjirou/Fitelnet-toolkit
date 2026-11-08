"""F221 SSH transport, adapted from yuu61/ix-toolkit (MIT)."""

import contextlib
import re
from collections.abc import Iterator, Sequence

from ..domain import (
    Hop,
    Target,
    UsageError,
    check_command_output,
    check_config_line_output,
    config_stopped_at,
    validate_show_commands,
)
from ..domain.redaction import validate_config_protocol
from .deps import missing_dependency

READ_TIMEOUT = 120
CONNECT_TIMEOUT = 20

PROMPT = r"(?m:^[^\r\n#> ()]*(?:\([^\r\n]*\))?[#>][ \t]*$)"


def open_jump_socket(hops: Sequence[Hop], dest_host: str, dest_port: int, clients: list):
    """Chain through `hops` with paramiko and return a direct-tcpip channel to the
    device, usable as netmiko's `sock`. Unlike netmiko's own ProxyJump handling
    this spawns no `ssh` ProxyCommand, which cannot work on Windows (paramiko's
    ProxyCommand.recv() selects on a pipe -> WinError 10038). Jump hosts
    authenticate with the IdentityFile from ssh_config (or the agent); only the
    device itself uses the inventory password. The opened clients are appended
    to `clients` so the caller can close them after the device session."""
    import paramiko

    sock = None
    for index, hop in enumerate(hops):
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        # Preserve the current connection policy: reject changed known keys,
        # accept unknown keys. Tightening that behavior is a separate CLI policy.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507
        client.connect(
            hostname=hop.host,
            port=hop.port,
            username=hop.user,
            key_filename=list(hop.keys) or None,
            sock=sock,
            timeout=CONNECT_TIMEOUT,
        )
        clients.append(client)
        if index + 1 < len(hops):
            nxt = hops[index + 1]
            target = (nxt.host, nxt.port)
        else:
            target = (dest_host, dest_port)
        sock = client.get_transport().open_channel("direct-tcpip", target, ("127.0.0.1", 0))
    return sock


class NetmikoSession:
    """F221 operations. Config responses never echo user-supplied secrets."""

    def __init__(self, conn, jump_clients: list, read_error: type[Exception]):
        self._conn = conn
        self._jump_clients = jump_clients
        self._read_error = read_error

    def _command(self, command: str) -> str:
        expect = PROMPT
        if command.startswith("show "):
            expect = rf"(?m:^{re.escape(self._conn.find_prompt())}[ \t]*$)"
        try:
            output = self._conn.send_command(
                command,
                expect_string=expect,
                read_timeout=READ_TIMEOUT,
                cmd_verify=False,
            )
        except self._read_error:
            raise UsageError(
                "ERROR: response incomplete; device state is uncertain; do not automatically retry"
            ) from None
        try:
            return check_command_output(command, output)
        except UsageError:
            if not command.startswith("show "):
                raise UsageError(f"ERROR: {command} rejected; response withheld") from None
            raise

    def show(self, cmd: str) -> str:
        validate_show_commands((cmd,))
        return self._command(cmd)

    def apply(self, lines: Sequence[str]) -> Iterator[str]:
        validate_config_protocol(tuple(lines))
        self._command("configure terminal")
        if "(config)" not in self._conn.find_prompt():
            raise UsageError("ERROR: configure terminal did not enter configuration mode")
        for number, line in enumerate(lines, 1):
            try:
                # Read a full line-anchored prompt; do not wait for an unwrapped echo.
                output = self._conn.send_command(
                    line,
                    expect_string=PROMPT,
                    read_timeout=READ_TIMEOUT,
                    cmd_verify=False,
                )
            except self._read_error:
                raise UsageError(
                    f"ERROR: {config_stopped_at(number, len(lines))}: response incomplete; "
                    "working.cfg may be partially edited; commit/save were not sent"
                ) from None
            check_config_line_output(number, len(lines), output, command=line)
            # The hostname can change; the prompt regexp deliberately permits that.
            if "(config" not in self._conn.find_prompt() and number != len(lines):
                raise UsageError(
                    f"ERROR: {config_stopped_at(number, len(lines))}: left configuration mode"
                )
            yield f"[OK] config line {number}; terminal response withheld"
        if "(config" in self._conn.find_prompt():
            self._command("end")
        self._conn.set_base_prompt()

    def commit(self) -> str:
        self._command("commit moff")
        return "[OK] commit response received; verify running.cfg and connectivity"

    def save(self) -> str:
        self._command("save moff")
        return "[OK] save response received; verify startup-config (working.cfg was saved)"

    def close(self) -> None:
        try:
            self._conn.disconnect()
        finally:
            _close_all(self._jump_clients)


def _close_all(clients: list) -> None:
    while clients:
        with contextlib.suppress(Exception):
            clients.pop().close()


def open_session(target: Target) -> NetmikoSession:  # noqa: C901
    # Driver callbacks and jump-channel cleanup share this connection lifecycle.
    try:
        from netmiko.base_connection import BaseConnection
        from netmiko.exceptions import ReadException
    except ImportError as exc:
        raise missing_dependency("netmiko") from exc

    class FitelnetConnection(BaseConnection):
        def session_preparation(self):
            self.set_base_prompt()
            current = self.find_prompt()
            if "(config" in current:
                raise UsageError("ERROR: SSH login must start in user or privileged mode")
            if current.rstrip().endswith(">"):
                if not self.secret:
                    raise UsageError("ERROR: set FITELNET_ENABLE_PASSWORD to enter enable 15")
                output = self.send_command(
                    "enable 15",
                    expect_string=r"(?im:password:[ \t]*$)|" + PROMPT,
                    read_timeout=READ_TIMEOUT,
                    strip_prompt=False,
                )
                if re.search(r"(?im)password:[ \t]*$", output):
                    self.send_command(
                        self.secret,
                        expect_string=PROMPT,
                        read_timeout=READ_TIMEOUT,
                        cmd_verify=False,
                        strip_command=False,
                    )
            if not self.find_prompt().rstrip().endswith("#"):
                raise UsageError("ERROR: privileged prompt required")
            self.set_base_prompt()
            output = self.send_command(
                "no more",
                expect_string=PROMPT,
                read_timeout=READ_TIMEOUT,
            )
            check_command_output("no more", output)

    params = {
        "host": target.host,
        "port": target.port,
        "username": target.username,
        "password": target.password or "",
        "secret": target.enable_password or "",
        "conn_timeout": CONNECT_TIMEOUT,
        "auth_timeout": CONNECT_TIMEOUT,
        "banner_timeout": CONNECT_TIMEOUT,
        "fast_cli": False,
        "system_host_keys": True,
    }
    if target.use_keys:
        params["use_keys"] = True
    if target.key_file:
        params["key_file"] = target.key_file
    jump_clients: list = []
    conn = None
    try:
        if target.hops:
            params["sock"] = open_jump_socket(target.hops, target.host, target.port, jump_clients)
        conn = FitelnetConnection(**params)
        return NetmikoSession(conn, jump_clients, ReadException)
    except Exception:
        if conn is not None:
            conn.disconnect()
        _close_all(jump_clients)
        raise
