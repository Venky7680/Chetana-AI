"""Small operator CLI.

    python -m app.cli hash-password 'S0me-Password!'
    python -m app.cli new-secret
    python -m app.cli list-operations
"""

from __future__ import annotations

import secrets
import sys

from .core.allowlist import OPERATIONS
from .core.security import hash_password


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(__doc__)
        return 1

    command, *rest = argv

    if command == "hash-password":
        if not rest:
            print("usage: hash-password <password>", file=sys.stderr)
            return 2
        print(hash_password(rest[0]))
        return 0

    if command == "new-secret":
        print(secrets.token_urlsafe(48))
        return 0

    if command == "list-operations":
        width = max(len(op_id) for op_id in OPERATIONS)
        for op_id in sorted(OPERATIONS):
            op = OPERATIONS[op_id]
            print(
                f"{op_id:<{width}}  R{int(op.tier)}  {op.min_role.name.lower():<8} "
                f"{op.method:<6} {op.path}"
            )
        return 0

    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
