// JavaScript port of deploy/n8n/contract.py for n8n Code nodes.
//
// The Python module is the specification. tests/gateway/test_n8n_workflow.py
// runs both implementations over the same inputs and fails on any divergence,
// so edit the two together. build_workflow.py inlines this file, unchanged,
// into the workflow's Code nodes; it must not require() anything.

const SUCCEEDED = "succeeded";
const FAILED_RETRYABLE = "failed_retryable";
const FAILED_TERMINAL = "failed_terminal";
const MAX_ATTEMPTS = 3;
const BACKOFF_BASE_S = 2.0;
const BACKOFF_CAP_S = 60.0;

const BLOCKED_MARKERS =
  /\b(403|401|blocked|forbidden|captcha|cloudflare|bot detection|access denied|rate.?limited|too many requests)\b/i;

const STATUS_MAP = {
  400: ["validation", false],
  401: ["auth", false],
  403: ["auth", false],
  413: ["validation", false],
  422: ["validation", false],
  429: ["rate_limit", true],
  500: ["server", true],
  502: ["server", true],
  503: ["capacity", true],
  504: ["deadline", true],
};

function cls(status, failureClass, retryable) {
  return { status, failure_class: failureClass, retryable };
}

function classifyHttp(code) {
  if (code >= 200 && code < 300) return cls(SUCCEEDED, null, false);
  let failureClass;
  let retryable;
  if (Object.prototype.hasOwnProperty.call(STATUS_MAP, code)) {
    [failureClass, retryable] = STATUS_MAP[code];
  } else if (code >= 400 && code < 500) {
    [failureClass, retryable] = ["validation", false];
  } else if (code >= 500) {
    [failureClass, retryable] = ["server", true];
  } else {
    [failureClass, retryable] = ["unknown", false];
  }
  return cls(retryable ? FAILED_RETRYABLE : FAILED_TERMINAL, failureClass, retryable);
}

function isMapping(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function classifyResultFailure(results) {
  const messages = results
    .filter(isMapping)
    .map((r) => String(r.error_message || r.error || ""))
    .join(" ");
  if (BLOCKED_MARKERS.test(messages)) return cls(FAILED_TERMINAL, "blocked_target", false);
  return cls(FAILED_TERMINAL, "unknown", false);
}

function classifyBody(body) {
  if (!isMapping(body)) return cls(FAILED_TERMINAL, "content_contract", false);
  if (!("success" in body) || !("results" in body)) {
    return cls(FAILED_TERMINAL, "content_contract", false);
  }
  const results = body.results;
  if (!Array.isArray(results) || results.length === 0) {
    return cls(FAILED_TERMINAL, "content_contract", false);
  }
  if (body.success !== true) return classifyResultFailure(results);
  for (const item of results) {
    if (!isMapping(item)) return cls(FAILED_TERMINAL, "content_contract", false);
    if (item.success !== true) return classifyResultFailure(results);
  }
  return cls(SUCCEEDED, null, false);
}

function classifyResponse(code, body) {
  const byStatus = classifyHttp(code);
  if (byStatus.status !== SUCCEEDED) return byStatus;
  return classifyBody(body);
}

function classifyTransportError() {
  return cls(FAILED_RETRYABLE, "network", true);
}

function shouldRetry(classification, attempt) {
  return Boolean(classification.retryable) && attempt < MAX_ATTEMPTS;
}

function retryDelaySeconds(attempt, retryAfter) {
  if (retryAfter !== undefined && retryAfter !== null && retryAfter !== "") {
    const parsed = Number(retryAfter);
    if (Number.isFinite(parsed) && parsed >= 0) return Math.min(parsed, BACKOFF_CAP_S);
  }
  return Math.min(Math.pow(BACKOFF_BASE_S, attempt), BACKOFF_CAP_S);
}

// No canonicalJson here on purpose: JSON.stringify formats numbers
// differently from Python (1.0 -> "1", 1e-07 -> "1e-7"), so a checksum over a
// re-serialized body would silently diverge. The workflow hashes the raw HTTP
// body bytes instead, which matches contract.raw_checksum(bytes) exactly.

const CODE_FENCE = "```";

function codeFenceCount(md) {
  return (md || "").split(CODE_FENCE).length - 1;
}

function inlineCodeCount(md) {
  const m = (md || "").match(/(?<!`)`[^`\n]+`(?!`)/g);
  return m ? m.length : 0;
}

function selectMarkdown(raw, fit) {
  const f = fit || "";
  if (!f.trim()) return { text: raw, source: "raw_markdown", reason: "fit_markdown is empty" };
  if (codeFenceCount(f) < codeFenceCount(raw)) {
    return { text: raw, source: "raw_markdown", reason: "fit_markdown dropped fenced code blocks" };
  }
  if (inlineCodeCount(f) < inlineCodeCount(raw)) {
    return { text: raw, source: "raw_markdown", reason: "fit_markdown dropped inline code spans" };
  }
  return { text: f, source: "fit_markdown", reason: "fit_markdown preserved code content" };
}

const SECRET_QUERY_KEYS = new Set([
  "token", "access_token", "api_key", "apikey", "key",
  "signature", "sig", "password", "secret",
]);

// Python urllib.parse.quote_plus: keep A-Za-z0-9 _ . - ~, space -> "+".
function quotePlus(s) {
  return encodeURIComponent(s)
    .replace(/[!'()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase())
    .replace(/%20/g, "+");
}

// Python urllib.parse.unquote_plus (errors="replace" keeps bad escapes).
function unquotePlus(s) {
  const spaced = s.replace(/\+/g, " ");
  try {
    return decodeURIComponent(spaced);
  } catch (e) {
    return spaced.replace(/%([0-9A-Fa-f]{2})/g, (m, h) => String.fromCharCode(parseInt(h, 16)));
  }
}

// Python redact_url: parse_qsl(keep_blank_values=True) + urlencode.
function redactUrl(url) {
  const hashAt = url.indexOf("#");
  const fragment = hashAt >= 0 ? url.slice(hashAt + 1) : null;
  const noFrag = hashAt >= 0 ? url.slice(0, hashAt) : url;
  const qAt = noFrag.indexOf("?");
  if (qAt < 0 || qAt === noFrag.length - 1) return url;
  const base = noFrag.slice(0, qAt);
  const pairs = noFrag
    .slice(qAt + 1)
    .split("&")
    .filter((part) => part.length > 0)
    .map((part) => {
      const eq = part.indexOf("=");
      const k = unquotePlus(eq >= 0 ? part.slice(0, eq) : part);
      const v = unquotePlus(eq >= 0 ? part.slice(eq + 1) : "");
      return [k, SECRET_QUERY_KEYS.has(k.toLowerCase()) ? "[REDACTED]" : v];
    });
  const query = pairs.map(([k, v]) => quotePlus(k) + "=" + quotePlus(v)).join("&");
  return base + (query ? "?" + query : "") + (fragment ? "#" + fragment : "");
}

// urllib.parse.urlsplit-equivalent check: http(s) scheme and a non-empty
// host, with no whitespace anywhere. Used to reject input before any request.
function isHttpUrl(url) {
  if (typeof url !== "string" || /\s/.test(url)) return false;
  const m = /^(https?):\/\/([^/?#]*)/i.exec(url);
  if (!m) return false;
  const authority = m[2].replace(/^[^@]*@/, "");
  const host = authority.replace(/:\d*$/, "");
  return host.length > 0;
}
