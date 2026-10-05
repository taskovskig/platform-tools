#!/usr/bin/env python3
"""Copy a shared chart and record the deployed application version in its metadata."""
import json
import re
import shutil
import sys
from pathlib import Path


def prepare(source, destination, version):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", version):
        raise ValueError("Invalid application version")
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Generated chart must be outside the shared chart")
    metadata = (source / "Chart.yaml").read_text()
    metadata, count = re.subn(r"^appVersion:.*$", "appVersion: " + json.dumps(version), metadata, flags=re.MULTILINE)
    if count != 1:
        raise ValueError("Shared chart must contain exactly one appVersion field")
    # Refuse an existing destination instead of overwriting another release copy.
    shutil.copytree(source, destination)
    (destination / "Chart.yaml").write_text(metadata)


if __name__ == "__main__":
    prepare(*sys.argv[1:])
