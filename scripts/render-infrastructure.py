#!/usr/bin/env python3
"""Render platform-owned infrastructure using validated project resource names."""
import json
import sys
from pathlib import Path


def render(directory, namespace, release, secret):
    directory.mkdir(parents=True, exist_ok=True)
    resources = {
        'namespace.json': {
            'apiVersion': 'v1', 'kind': 'Namespace',
            'metadata': {'name': namespace, 'labels': {
                'pod-security.kubernetes.io/enforce': 'restricted',
                'pod-security.kubernetes.io/enforce-version': 'v1.37',
            }},
        },
        'db-serviceaccount.json': {
            'apiVersion': 'v1', 'kind': 'ServiceAccount',
            'metadata': {'name': release, 'namespace': namespace},
            'automountServiceAccountToken': False,
        },
        'db.values.json': {
            'fullnameOverride': release,
            'settings': {'existingSecret': secret},
            'serviceAccount': {'name': release},
        },
    }
    for filename, resource in resources.items():
        (directory / filename).write_text(json.dumps(resource, indent=2) + '\n')


if __name__ == '__main__':
    render(Path(sys.argv[1]), *sys.argv[2:])
