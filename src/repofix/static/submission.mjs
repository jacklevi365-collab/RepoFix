// Retain a request identity across ambiguous network failures. Acceptance starts
// a new submission identity; this cache contains task options, never API keys.
export function createSubmission(send, makeId = () => crypto.randomUUID()) {
  const pending = new Map();
  return async function submit(payload) {
    const body = JSON.stringify(payload);
    if (!pending.has(body)) pending.set(body, makeId());
    const result = await send("/api/jobs", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": pending.get(body),
      },
      body,
    });
    pending.delete(body);
    return result;
  };
}
