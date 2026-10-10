#!/usr/bin/env python3
"""
Assert the *rendered* compose topology is private (SPEC.md M2, AC-03/AC-07).

test_security_gateway_topology.py parses docker-compose.yml as written. This
checks what `docker compose config` actually produces, which is what the daemon
would run -- anchors, variable interpolation and overrides all resolved.

Usage:
    docker compose config | python deploy/gateway/check_rendered_topology.py
    python deploy/gateway/check_rendered_topology.py rendered.yml
"""

from __future__ import annotations

import sys

import yaml

SERVICE = "crawl4ai"
NETWORK = "automation_internal"


def check(rendered: dict) -> list[str]:
    problems: list[str] = []
    services = rendered.get("services") or {}

    svc = services.get(SERVICE)
    if svc is None:
        return [f"service {SERVICE!r} missing from rendered config"]

    for name, other in services.items():
        if other.get("ports"):
            problems.append(f"service {name!r} publishes host ports: {other['ports']}")

    networks = svc.get("networks") or {}
    names = networks if isinstance(networks, (list, dict)) else []
    if NETWORK not in names:
        problems.append(f"{SERVICE} is not attached to {NETWORK}: {networks!r}")

    image = svc.get("image", "")
    if "latest" in image:
        problems.append(f"{SERVICE} resolves to a mutable tag: {image}")
    if image.startswith(("unclecode/crawl4ai", "docker.io/unclecode/crawl4ai")):
        problems.append(
            f"{SERVICE} resolves to the stock upstream image, which lacks this "
            f"fork's baked-in config.yml hardening: {image}"
        )

    if svc.get("read_only") is not True:
        problems.append("root filesystem is not read-only")
    if svc.get("privileged"):
        problems.append("service runs privileged")

    return problems


def main(argv: list[str]) -> int:
    source = open(argv[1]) if len(argv) > 1 else sys.stdin
    rendered = yaml.safe_load(source)
    problems = check(rendered)
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"rendered topology OK: {rendered['services'][SERVICE].get('image')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
