import test from "node:test";
import assert from "node:assert/strict";
import { createSubmission } from "../../src/repofix/static/submission.mjs";

test("an ambiguous failure retries the same payload with the same identity", async () => {
  const requests = [];
  let fail = true;
  let sequence = 0;
  const submit = createSubmission(async (path, options) => {
    requests.push(options);
    if (fail) {
      fail = false;
      throw new Error("Connection lost after the server may have accepted it");
    }
    return { id: "accepted-job" };
  }, () => `request-${++sequence}`);
  const payload = { task_id: "demo-tinybug", mode: "demo" };
  await assert.rejects(submit(payload));
  assert.equal((await submit(payload)).id, "accepted-job");
  assert.equal(requests[0].headers["Idempotency-Key"], requests[1].headers["Idempotency-Key"]);
  // A deliberate new run after known acceptance receives a new identity.
  await submit(payload);
  assert.notEqual(requests[1].headers["Idempotency-Key"], requests[2].headers["Idempotency-Key"]);
});

test("changing options does not lose the uncertain original request identity", async () => {
  const keys = [];
  let fail = true;
  let sequence = 0;
  const submit = createSubmission(async (_, options) => {
    keys.push(options.headers["Idempotency-Key"]);
    if (fail) throw new Error("uncertain");
    return { id: "accepted" };
  }, () => `request-${++sequence}`);
  await assert.rejects(submit({ task_id: "a" }));
  await assert.rejects(submit({ task_id: "b" }));
  fail = false;
  await submit({ task_id: "a" });
  assert.notEqual(keys[0], keys[1]);
  assert.equal(keys[0], keys[2]);
});
