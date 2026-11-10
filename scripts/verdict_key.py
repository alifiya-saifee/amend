"""Make the Ed25519 seed for VERDICT_SIGNING_KEY without ever printing it.

    python -m scripts.verdict_key [path]      (default: ~/amend-verdict-signing-key.txt)

Writes the seed (64 hex characters) to that file, readable by you only, and prints just the PUBLIC key and its
fingerprint (the key id shown on every verdict and in the README). Paste the file's contents into Render as
VERDICT_SIGNING_KEY, then delete the file. Refuses to overwrite an existing file; with an existing file it only prints
the public key and fingerprint for the seed in it.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def public_of(seed_hex: str) -> tuple[str, str]:
    from amend.verdict import seed_from
    pub = base64.b64encode(Ed25519PrivateKey.from_private_bytes(seed_from(seed_hex)).public_key()
                           .public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    return pub, hashlib.sha256(pub.encode()).hexdigest()[:16]  # same key id as amend.verdict.key_id


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "~/amend-verdict-signing-key.txt").expanduser()
    if path.exists():
        seed = path.read_text().strip()
        print(f"{path} already exists: not overwritten.")
    else:
        seed = secrets.token_bytes(32).hex()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(seed + "\n")
        print(f"Seed written to {path} (only you can read it). Paste its contents into Render as VERDICT_SIGNING_KEY, then delete it.")
    pub, kid = public_of(seed)
    print(f"public key (Ed25519, base64): {pub}")
    print(f"fingerprint (key id):         {kid}")


if __name__ == "__main__":
    main()
