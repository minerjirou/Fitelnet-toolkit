"""F221 config terminal responses are withheld; never guess secret syntax."""

from .errors import UsageError


def validate_config_protocol(lines: tuple[str, ...]) -> None:
    reserved = (
        "commit",
        "refresh",
        "save",
        "reset",
        "restart",
        "reload",
        "load",
        "discard",
        "restore",
        "rollback",
        "enable",
        "disable",
        "configure",
        "do",
        "exec",
        "run",
        "shell",
        "quit",
        "logout",
    )
    for number, line in enumerate(lines, 1):
        if not line.strip() or not all(c.isprintable() for c in line):
            raise UsageError(f"ERROR: config line {number}: use one printable command per line")
        first = line.strip().split()[0].lower()
        if any(word.startswith(first) for word in reserved):
            raise UsageError(
                f"ERROR: config line {number}: operational command; use dedicated flags"
            )
        if any(c in line for c in "?;|"):
            raise UsageError(
                f"ERROR: config line {number}: interactive or chained input unsupported"
            )
        if first in {"crypto", "certificate", "banner"}:
            raise UsageError(
                f"ERROR: config line {number}: interactive key/certificate/banner input unsupported"
            )
