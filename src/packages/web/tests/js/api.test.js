import test from "node:test";
import assert from "node:assert/strict";

// The module reads window.location.origin at call time, so the shim must be
// in place before it is imported.
globalThis.window = { location: { origin: "http://x" } };

const { getJson, api, ApiError } = await import("../../helpmate_web/static/js/api.js");

function stubFetch(handler) {
  const calls = [];
  global.fetch = async (url) => {
    calls.push(url);
    return handler(url);
  };
  return calls;
}

function jsonResponse(status, body) {
  return {
    status,
    statusText: `status ${status}`,
    json: async () => body,
  };
}

test("dtm: 0 and starts: 0 are forwarded, undefined/null/empty are dropped", async () => {
  const calls = stubFetch(() => jsonResponse(200, { ok: true }));
  await getJson("/v1/mine", {
    dtm: 0,
    starts: 0,
    ends: undefined,
    all: null,
    fen: "",
    material: "KQvK",
  });
  const url = String(calls[0]);
  assert.ok(url.includes("dtm=0"), `expected dtm=0 in ${url}`);
  assert.ok(url.includes("starts=0"), `expected starts=0 in ${url}`);
  assert.ok(!url.includes("ends="), `undefined should be dropped: ${url}`);
  assert.ok(!url.includes("all="), `null should be dropped: ${url}`);
  assert.ok(!url.includes("fen="), `empty string should be dropped: ${url}`);
  assert.ok(url.includes("material=KQvK"));
});

test("a 202 response resolves and returns status + body", async () => {
  stubFetch(() => jsonResponse(202, { progress: 0.5 }));
  const result = await getJson("/v1/materials/KQvK/stats");
  assert.deepEqual(result, { status: 202, body: { progress: 0.5 } });
});

test("a 400 with the error envelope throws an ApiError with status/code/message/hint", async () => {
  stubFetch(() =>
    jsonResponse(400, { error: { code: "invalid_fen", message: "bad", hint: "h" } })
  );
  await assert.rejects(
    () => getJson("/v1/probe", { fen: "nope" }),
    (err) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.status, 400);
      assert.equal(err.code, "invalid_fen");
      assert.equal(err.message, "bad");
      assert.equal(err.hint, "h");
      return true;
    }
  );
});

test("a 500 with a non-JSON body still throws an ApiError instead of crashing", async () => {
  global.fetch = async () => ({
    status: 500,
    statusText: "Internal Server Error",
    json: async () => {
      throw new SyntaxError("Unexpected end of JSON input");
    },
  });
  await assert.rejects(
    () => getJson("/v1/health"),
    (err) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.status, 500);
      assert.equal(err.code, "error");
      assert.equal(err.message, "Internal Server Error");
      return true;
    }
  );
});

test("a network failure surfaces as an ApiError with code 'network', not a raw TypeError", async () => {
  global.fetch = async () => {
    throw new TypeError("fetch failed");
  };
  await assert.rejects(
    () => getJson("/v1/health"),
    (err) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.status, 0);
      assert.equal(err.code, "network");
      assert.equal(err.message, "cannot reach the server");
      assert.equal(err.hint, null);
      return true;
    }
  );
});

test("api.probe forwards the fen param", async () => {
  const calls = stubFetch(() => jsonResponse(200, {}));
  await api.probe("8/8/8/8/8/8/8/K6k w - - 0 1");
  assert.ok(String(calls[0]).includes("fen="));
});
