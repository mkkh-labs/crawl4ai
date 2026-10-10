"""
Server-owned browser defaults for request-built BrowserConfigs.

The permanent browser is built from config.yml (`crawler.browser.extra_args`
and `crawler.browser.kwargs`). /crawl requests were built from the request
body alone, so an ordinary request (`browser_config: {}`) never carried those
fields, its pool signature never matched, and every request launched a second
Chromium while the permanent one sat idle. The operator's browser policy
(--disable-dev-shm-usage, text_mode, ...) also silently never applied.

`apply_server_browser_defaults` closes that gap without widening what a
request may control:

* `extra_args` is server-owned. An untrusted body that sets it is already
  refused with 400, so the server's list is always applied.
* each `kwargs` default fills only a field the request did not set
  explicitly; anything the caller chose still wins.
"""

from __future__ import annotations

import os
from typing import Any

from crawl4ai import BrowserConfig


def chromium_sandbox_enabled() -> bool:
    return os.environ.get("CRAWL4AI_CHROMIUM_SANDBOX", "false").lower() == "true"


def server_extra_args(config: dict, sandbox: bool | None = None) -> list[str]:
    """Chromium flags from config.yml, minus --no-sandbox when sandboxed.

    `sandbox` defaults to CRAWL4AI_CHROMIUM_SANDBOX; server.py passes its own
    module-level CHROMIUM_SANDBOX so that switch keeps working as before.
    """
    if sandbox is None:
        sandbox = chromium_sandbox_enabled()
    args = list(config["crawler"]["browser"].get("extra_args", []))
    if sandbox:
        args = [a for a in args if a != "--no-sandbox"]
    return args


def requested_fields(raw: Any) -> set[str]:
    """Field names a request body set, in either serialized shape.

    Accepts {"type": "BrowserConfig", "params": {...}} and a flat dict.
    """
    if not isinstance(raw, dict):
        return set()
    fields = {k for k in raw if k not in ("type", "params")}
    params = raw.get("params")
    if isinstance(params, dict):
        fields |= set(params)
    return fields


def apply_server_browser_defaults(
    bc: BrowserConfig, raw_request: Any, config: dict
) -> BrowserConfig:
    """Give a request-built config the server's browser defaults (see module doc)."""
    explicit = requested_fields(raw_request)
    bc.extra_args = server_extra_args(config)
    for key, value in config["crawler"]["browser"].get("kwargs", {}).items():
        if key not in explicit and hasattr(bc, key):
            setattr(bc, key, value)
    return bc
