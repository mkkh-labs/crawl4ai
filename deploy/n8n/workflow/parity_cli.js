// Test harness: evaluates contract.js on JSON cases from stdin (one array),
// prints the results as JSON. Used only by tests/gateway/test_n8n_workflow.py.
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, "contract.js"), "utf8"), ctx);

const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = cases.map((c) => {
  switch (c.fn) {
    case "classifyResponse":
      return ctx.classifyResponse(c.status, c.body);
    case "shouldRetry":
      return ctx.shouldRetry(c.classification, c.attempt);
    case "retryDelaySeconds":
      return ctx.retryDelaySeconds(c.attempt, c.retry_after);
    case "selectMarkdown":
      return ctx.selectMarkdown(c.raw, c.fit);
    case "isHttpUrl":
      return ctx.isHttpUrl(c.url);
    case "redactUrl":
      return ctx.redactUrl(c.url);
    default:
      throw new Error("unknown fn " + c.fn);
  }
});
process.stdout.write(JSON.stringify(out));
