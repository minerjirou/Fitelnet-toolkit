"""Small real SSH server for the documented F221 protocol; no physical router."""

import contextlib
import logging
import socket
import threading

import paramiko

logging.getLogger(__name__).addHandler(logging.NullHandler())
logging.getLogger(__name__).propagate = False


class Server(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        if username == "admin" and password == "test-password":
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def check_channel_pty_request(self, *args):
        return True

    def check_channel_shell_request(self, channel):
        return True


class FakeFitelnet:
    def __init__(self, hostname="f221", user_mode=False):
        self.hostname = hostname
        self.user_mode = user_mode
        self.commands = []
        self.responses = {}
        self.working = []
        self.running = []
        self.startup = []
        self.key = paramiko.RSAKey.generate(2048)
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen()
        self.port = self.socket.getsockname()[1]
        self.transports = []
        self.stopped = False

    def __enter__(self):
        threading.Thread(target=self.serve, daemon=True).start()
        return self

    def __exit__(self, *args):
        self.stopped = True
        for transport in self.transports:
            transport.close()
        self.socket.close()

    def serve(self):
        while not self.stopped:
            try:
                client, _ = self.socket.accept()
            except OSError:
                return
            threading.Thread(target=self.connection, args=(client,), daemon=True).start()

    def connection(self, client):
        transport = paramiko.Transport(client)
        transport.set_log_channel(__name__)
        self.transports.append(transport)
        transport.add_server_key(self.key)
        try:
            transport.start_server(server=Server())
            chan = transport.accept(10)
            if chan is None:
                return
            self.shell(chan)
        except (EOFError, OSError, paramiko.SSHException):
            pass
        finally:
            transport.close()

    def shell(self, chan):
        config = False
        privileged = not self.user_mode
        password_pending = False

        def prompt():
            mode = "(config)" if config else ""
            return self.hostname + mode + ("#" if privileged else ">")

        def reply(text=""):
            chan.sendall(text + "\r\n" + prompt())

        reply()
        buffer = b""
        while not chan.closed:
            data = chan.recv(4096)
            if not data:
                return
            # Typical terminal echo. Password input is deliberately not echoed.
            if not password_pending:
                chan.sendall(data)
            buffer += data
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                line = raw.decode().strip()
                if password_pending:
                    privileged = line == "enable-secret"
                    password_pending = False
                    reply()
                    continue
                if not line:
                    reply()
                    continue
                self.commands.append(line)
                if line in self.responses:
                    reply(self.responses[line])
                elif line == "enable 15":
                    password_pending = True
                    chan.sendall("password:")
                elif not privileged:
                    reply("% Permission denied")
                elif line == "no more":
                    reply()
                elif line == "show version":
                    reply("FITELnet F221 Version V01.21(00)")
                elif line == "show lte-module status":
                    reply("status : connected\r\nRSSI : -69dBm")
                elif line in {"show running.cfg", "show working.cfg", "show startup-config"}:
                    content = {
                        "show running.cfg": self.running,
                        "show working.cfg": self.working,
                        "show startup-config": self.startup,
                    }[line]
                    reply("\r\n".join(content))
                elif line == "configure terminal":
                    config = True
                    reply()
                elif line in {"end", "exit"} and config:
                    config = False
                    reply()
                elif line == "commit moff" and not config:
                    self.running = self.working.copy()
                    reply("refreshing\r\nDone")
                elif line == "save moff" and not config:
                    self.startup = self.working.copy()
                    reply("% saving working-config\r\n100%")
                elif config:
                    self.working.append(line)
                    if line.startswith("hostname "):
                        self.hostname = line.split()[1]
                    reply()
                else:
                    reply("% Unknown command")
        with contextlib.suppress(OSError):
            chan.close()
