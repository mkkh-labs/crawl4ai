"""
Crawl4AI Gateway Console -- a Streamlit operator UI for the private gateway.

Run:  streamlit run deploy/ui/app.py
Env:  CRAWL4AI_BASE_URL   (default http://crawl4ai:11235)
      CRAWL4AI_API_TOKEN  or CRAWL4AI_API_TOKEN_FILE (default /run/secrets/api_token)
      CONSOLE_HISTORY_PATH (optional JSONL of run provenance, never page bodies)

Crawled content is untrusted: it is only ever rendered as plain text
(st.code / st.json), never as HTML or interpreted markdown.
"""

from __future__ import annotations

import json
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import console as con  # noqa: E402

st.set_page_config(
    page_title="Crawl4AI Gateway Console",
    page_icon=":material/travel_explore:",
    layout="wide",
)


def _settings() -> con.GatewaySettings:
    # Not cached: reading the secret file each run means a rotated token is
    # picked up without restarting the console.
    return con.load_settings()


def _require_settings() -> con.GatewaySettings:
    try:
        return _settings()
    except con.ConsoleError as exc:
        st.error(str(exc), icon=":material/key_off:")
        st.stop()


@st.cache_data(ttl=15, show_spinner=False)
def _health(base_url: str) -> con.Health:
    # base_url keys the cache (the token never enters a cache key); callers
    # have already validated settings via _require_settings().
    return con.check_health(_settings())


def _status_badge(health: con.Health) -> None:
    if not health.ok:
        st.error(
            f"Gateway unreachable (HTTP {health.status_code}, {health.error})",
            icon=":material/cloud_off:",
        )
    elif not health.safe_version:
        st.warning(
            f"Gateway {health.version} is below the minimum safe version",
            icon=":material/gpp_bad:",
        )
    else:
        st.success(
            f"Gateway {health.version} healthy · {health.latency_ms} ms",
            icon=":material/verified_user:",
        )


# ── pages ────────────────────────────────────────────────────────────────────


def page_status() -> None:
    settings = _require_settings()
    st.title("Gateway status")
    health = _health(settings.base_url)
    _status_badge(health)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Version", health.version or "—")
    c2.metric("Latency", f"{health.latency_ms:.0f} ms")
    c3.metric(
        "Min safe version",
        ".".join(map(str, con.e2e.MIN_SAFE_VERSION)),
        delta="met" if health.safe_version else "not met",
        delta_color="normal" if health.safe_version else "inverse",
    )
    c4.metric("Token", settings.token_source_label)
    st.caption(f"Endpoint: `{settings.base_url}` (private network only)")
    if st.button("Refresh", icon=":material/refresh:"):
        _health.clear()
        st.rerun()


def page_crawl() -> None:
    settings = _require_settings()
    st.title("Crawl")
    health = _health(settings.base_url)
    _status_badge(health)
    if not health.ok:
        st.stop()

    with st.form("crawl"):
        urls_text = st.text_area(
            "URLs (one per line)",
            placeholder="https://example.com/",
            help=f"http(s) only, up to {con.MAX_URLS_PER_BATCH} per batch.",
        )
        left, right = st.columns(2)
        with left:
            cache_mode = st.selectbox("Cache mode", con.CACHE_MODES)
            variant = st.selectbox(
                "Markdown",
                con.MARKDOWN_VARIANTS,
                help="auto = contract rule: fit unless it lost code, else raw.",
            )
            timeout_s = st.slider("Request timeout (s)", 30, con.MAX_TIMEOUT_S, 180)
        with right:
            css_selector = st.text_input("CSS selector (optional)")
            excluded = st.text_input(
                "Excluded tags (comma separated)", value="nav,footer"
            )
            wait_for = st.text_input("Wait for (css:… or optional)")
        with st.expander("Advanced"):
            a1, a2 = st.columns(2)
            wct = a1.number_input("Word count threshold", 0, 1000, 0)
            page_timeout = a2.number_input(
                "Page timeout (ms)", 1_000, 60_000, 60_000, step=1_000
            )
            ext = st.checkbox("Exclude external links")
            overlays = st.checkbox("Remove overlay elements")
            robots = st.checkbox("Respect robots.txt")
        submitted = st.form_submit_button("Run crawl", icon=":material/play_arrow:")

    if not submitted:
        return
    try:
        urls = con.parse_urls(urls_text)
        cfg = con.build_crawler_config(
            con.CrawlOptions(
                cache_mode=cache_mode,
                css_selector=css_selector,
                excluded_tags=tuple(excluded.split(",")),
                word_count_threshold=int(wct) or None,
                wait_for=wait_for,
                page_timeout_ms=int(page_timeout),
                exclude_external_links=ext,
                remove_overlay_elements=overlays,
                check_robots_txt=robots,
            )
        )
    except con.ConsoleError as exc:
        st.error(str(exc))
        return

    views: list[con.RunView] = []
    progress = st.progress(0.0, text="Starting…")
    for i, url in enumerate(urls, start=1):
        progress.progress((i - 1) / len(urls), text=f"Crawling {url}")
        view = con.run_crawl(
            settings, url, cfg, health.version or "unknown", timeout_s, variant
        )
        con.append_history(settings.history_path, view.record)
        views.append(view)
    progress.progress(1.0, text="Done")
    st.session_state["last_runs"] = views

    ok = sum(v.record["status"] == con.c.SUCCEEDED for v in views)
    st.subheader(f"{ok}/{len(views)} succeeded")
    for view in views:
        _render_run(view)


def _render_run(view: con.RunView) -> None:
    rec = view.record
    succeeded = rec["status"] == con.c.SUCCEEDED
    icon = ":material/check_circle:" if succeeded else ":material/error:"
    label = f"{rec['source_url']} — {rec['status']}"
    if rec.get("failure_class"):
        label += f" ({rec['failure_class']})"
    with st.expander(label, icon=icon, expanded=succeeded):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("HTTP", view.http_status if view.http_status is not None else "—")
        m2.metric("Attempts", rec["attempts"])
        m3.metric("Markdown chars", len(view.markdown))
        m4.metric("Code fences", con.c.code_fence_count(view.markdown) // 2)
        st.caption(f"Markdown: {view.markdown_source} — {view.markdown_reason}")
        md_tab, prov_tab = st.tabs(["Markdown", "Provenance"])
        with md_tab:
            if view.markdown:
                st.code(view.markdown, language="markdown", wrap_lines=True, height=420)
            else:
                st.info("No markdown in this response.")
        with prov_tab:
            st.json(con.summarize(rec), expanded=True)
            if rec.get("failures"):
                st.json(rec["failures"], expanded=False)
        d1, d2 = st.columns(2)
        d1.download_button(
            "Download CrawlRun JSON",
            json.dumps(rec, indent=2, default=str),
            file_name=f"{rec['run_id']}.json",
            mime="application/json",
            key=f"json-{rec['run_id']}",
            icon=":material/download:",
        )
        d2.download_button(
            "Download markdown",
            view.markdown or "",
            file_name=f"{rec['run_id']}.md",
            mime="text/markdown",
            key=f"md-{rec['run_id']}",
            disabled=not view.markdown,
            icon=":material/description:",
        )


def page_history() -> None:
    settings = _require_settings()
    st.title("Run history")
    if not settings.history_path:
        st.info(
            "History is off. Set CONSOLE_HISTORY_PATH to keep a provenance log "
            "(run metadata only, never page content)."
        )
        runs = st.session_state.get("last_runs", [])
        if runs:
            st.dataframe([con.summarize(v.record) for v in runs], width="stretch")
        return
    rows = list(reversed(con.read_history(settings.history_path)))
    if not rows:
        st.info("No runs recorded yet.")
        return
    ok = sum(r.get("status") == con.c.SUCCEEDED for r in rows)
    c1, c2, c3 = st.columns(3)
    c1.metric("Runs", len(rows))
    c2.metric("Succeeded", ok)
    c3.metric("Success rate", f"{ok / len(rows):.0%}")
    st.dataframe(rows, width="stretch", hide_index=True)


def page_selftest() -> None:
    settings = _require_settings()
    st.title("Security self-test")
    st.write(
        "Live checks against the running gateway: version floor, token "
        "enforcement, the GHSA-5w5p config-laundering gate and metadata-SSRF "
        "refusal. Every probe is safe against a vulnerable server too — none "
        "can send data off this machine."
    )
    if st.button("Run self-test", icon=":material/shield:"):
        with st.spinner("Probing gateway…"):
            checks = con.self_test(settings)
        passed = sum(ch.passed for ch in checks)
        if passed == len(checks):
            st.success(f"All {len(checks)} checks passed", icon=":material/verified:")
        else:
            st.error(f"{len(checks) - passed} of {len(checks)} checks failed")
        for ch in checks:
            st.write(
                f"{':material/check_circle:' if ch.passed else ':material/cancel:'} "
                f"**{ch.name}** — {ch.detail}"
            )


nav = st.navigation(
    [
        st.Page(page_status, title="Status", icon=":material/monitor_heart:"),
        st.Page(page_crawl, title="Crawl", icon=":material/travel_explore:"),
        st.Page(page_history, title="History", icon=":material/history:"),
        st.Page(page_selftest, title="Self-test", icon=":material/shield:"),
    ]
)
nav.run()
