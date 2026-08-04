#!/usr/bin/env python3
"""Create admin.json — the encrypted GitHub token that unlocks edit mode on the site.

    python3 make_admin.py

Prompts for a fine-grained GitHub PAT and a password, then writes admin.json:
the token encrypted with AES-256-GCM under a PBKDF2-SHA256(600k) key derived from
the password. Neither value is stored anywhere else, and neither is ever echoed.

admin.json lands in a PUBLIC repo, so the password is the only thing standing
between a downloader and the token. Use a long random one, and scope the PAT to
this repository with Contents: Read and write and nothing else.
"""

import base64
import getpass
import json
import os
import pathlib
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 600_000
REPO = "gabiprun/play-apps-hub"
OUT = pathlib.Path(__file__).parent / "admin.json"


def b64(raw):
    return base64.b64encode(raw).decode()


def main():
    print(__doc__.strip().split("\n\n", 1)[1])
    print()

    token = getpass.getpass("GitHub fine-grained PAT (github_pat_…): ").strip()
    if not token:
        sys.exit("no token given")
    if not token.startswith(("github_pat_", "ghp_")):
        print("warning: that does not look like a GitHub token, continuing anyway")

    password = getpass.getpass("Admin password: ")
    if len(password) < 10:
        sys.exit("password too short — use at least 10 characters, ideally random")
    if password != getpass.getpass("Confirm password: "):
        sys.exit("passwords do not match")

    salt = os.urandom(16)
    iv = os.urandom(12)
    import hashlib

    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS, dklen=32)
    ciphertext = AESGCM(key).encrypt(iv, token.encode(), None)

    OUT.write_text(
        json.dumps(
            {
                "repo": REPO,
                "kdf": {
                    "name": "PBKDF2",
                    "hash": "SHA-256",
                    "iterations": ITERATIONS,
                    "salt": b64(salt),
                },
                "iv": b64(iv),
                "ciphertext": b64(ciphertext),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nwrote {OUT.name}. Commit and push it, then click the lock icon on the site.")


if __name__ == "__main__":
    main()
