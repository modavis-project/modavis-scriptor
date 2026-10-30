/** Exercise generated guards and the network boundary without a running server. */
import assert from "node:assert/strict";
import { after, test } from "node:test";
import { readFile, writeFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { transpileModule, ModuleKind, ScriptTarget } from "typescript";

const temporary = await mkdtemp(join(tmpdir(), "scriptor-contract-tests-"));
after(() => rm(temporary, { recursive: true, force: true }));
await writeFile(join(temporary, "package.json"), '{"type":"module"}');
for (const name of ["schema", "contracts.generated", "api"]) {
  const source = await readFile(resolve(`lib/graphics/${name}.ts`), "utf8");
  const { outputText } = transpileModule(source, {
    compilerOptions: { module: ModuleKind.ESNext, target: ScriptTarget.ES2022 },
  });
  await writeFile(join(temporary, `${name}.js`), outputText);
}
const contracts = await import(pathToFileURL(join(temporary, "contracts.generated.js")));
const { graphicsApi, request, ApiError } = await import(pathToFileURL(join(temporary, "api.js")));
const { matchesSchema } = await import(pathToFileURL(join(temporary, "schema.js")));
const fixture = JSON.parse(
  await readFile("services/graphics/example/processed/result.json", "utf8"),
);
fixture.regions = fixture.regions.map((region) => ({
  ...region,
  effective: region.parsed,
  status: "unreviewed",
  version: 0,
  review: null,
}));
fixture.review_events = [];
fixture.markdown = "Immutable fixture materialized for transport checks";
fixture.raw_markdown = "Scharff\nIV-VI";
fixture.immutable_result_sha256 = "a".repeat(64);
fixture.integrity = {
  coverage: "frozen-example",
  verified_files: {},
  unverified_files: [],
  note: "Synthetic transport materialization of the real frozen fixture",
};

async function withResponse(response, action) {
  const original = globalThis.fetch;
  globalThis.fetch = async () => response;
  try {
    return await action();
  } finally {
    globalThis.fetch = original;
  }
}

test("generated output guard accepts the real frozen region/OCR/corpus structures", () => {
  assert.equal(contracts.isGraphicsResult(fixture), true);
  assert.equal(contracts.isConfig_Output(contracts.defaultConfig), true);
  assert.equal(contracts.isConfig_Input({}), true); // Pydantic defaults are optional on input only.
  assert.equal(contracts.isConfig_Output({}), false);
});

test("malformed nested result/coordinate/OCR/candidate data is rejected before rendering", () => {
  for (const mutate of [
    (value) => {
      value.regions[0].bbox_normalized = [0, 0, 1];
    },
    (value) => {
      value.regions[0].bbox_normalized[0] = NaN;
    },
    (value) => {
      value.regions[2].candidates[0].evidence[0].component_id = 32;
    },
    (value) => {
      value.regions[0].ocr.psm = "6";
    },
    (value) => {
      value.regions[0].effective.kind = "automatic_acceptance";
    },
    (value) => {
      delete value.integrity;
    },
    (value) => {
      value.image.width = 0;
    },
  ]) {
    const invalid = structuredClone(fixture);
    mutate(invalid);
    assert.equal(contracts.isGraphicsResult(invalid), false);
  }
});

test("runtime JSON Schema constraints match request enums, tuple bounds and Unicode lengths", () => {
  assert.equal(contracts.isConfig_Input({ language: "deu", regions: [[0, 0, 0.2, 0.2]] }), true);
  assert.equal(contracts.isConfig_Input({ language: "invented" }), false);
  assert.equal(contracts.isConfig_Input({ regions: [[-0.1, 0, 0.2, 0.2]] }), false);
  assert.equal(contracts.isConfig_Input({ regions: [[0, 0, 0.2, 0.2, 0.2]] }), false);
  assert.equal(
    contracts.isReview_Input({ action: "accept", reviewer: "x", rationale: "a long rationale" }),
    false,
  );
  assert.equal(matchesSchema("😀", { type: "string", minLength: 2 }, {}), false);
  assert.equal(
    matchesSchema({ inherited: 1 }, { type: "object", required: ["missing"] }, {}),
    false,
  );
  assert.equal(
    matchesSchema(
      JSON.parse('{"__proto__": 1}'),
      { type: "object", properties: {}, additionalProperties: false },
      {},
    ),
    false,
  );
});

test("HTTP 200 with a wrong shape or malformed JSON raises a contract error", async () => {
  await withResponse(Response.json({ regions: [] }), async () => {
    await assert.rejects(
      graphicsApi.run("a"),
      (error) => error instanceof ApiError && error.code === "contract",
    );
  });
  await withResponse(new Response("not-json", { status: 200 }), async () => {
    await assert.rejects(graphicsApi.run("a"), (error) => error.code === "contract");
  });
});

test("HTTP conflict, FastAPI validation and plain middleware errors preserve useful diagnostics", async () => {
  for (const [response, expected] of [
    [
      Response.json({ detail: "Review changed. Reload before saving." }, { status: 409 }),
      /Review changed/,
    ],
    [
      Response.json(
        {
          detail: [
            { loc: ["body", "reviewer"], msg: "String too short", type: "string_too_short" },
          ],
        },
        { status: 422 },
      ),
      /body.reviewer: String too short/,
    ],
    [
      new Response("Upload exceeds limit", {
        status: 413,
        headers: { "content-type": "text/plain" },
      }),
      /Upload exceeds limit/,
    ],
    [
      new Response("<html>internal secrets</html>", {
        status: 500,
        headers: { "content-type": "text/html" },
      }),
      /^Grafikdienst: HTTP 500$/,
    ],
  ]) {
    await withResponse(response, async () =>
      assert.rejects(graphicsApi.run("a"), (error) => expected.test(error.message)),
    );
  }
});

test("network failures and aborts are distinguished; malformed writes never reach fetch", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => {
      throw new Error("private network details");
    };
    await assert.rejects(
      graphicsApi.list(),
      (error) => error.code === "network" && !error.message.includes("private"),
    );
    globalThis.fetch = async () => {
      throw new DOMException("canceled", "AbortError");
    };
    await assert.rejects(graphicsApi.list(), (error) => error.name === "AbortError");
    globalThis.fetch = async () => {
      assert.fail("invalid input reached the network");
    };
    assert.throws(() => graphicsApi.rerun("a", { language: "invalid" }), /Ungültige Verarbeitung/);
    assert.throws(
      () => graphicsApi.review("a", "r001", { action: "accept", reviewer: "x" }),
      /Ungültige Entscheidung/,
    );
  } finally {
    globalThis.fetch = original;
  }
});

test("validated responses return without discarding literal OCR or extension provenance", async () => {
  const value = { ...fixture, future_provenance: { literal: "Scharff" } };
  await withResponse(Response.json(value), async () => {
    const received = await request("/test", contracts.isGraphicsResult);
    assert.equal(received.regions[2].raw_text, "Scharff\nIV-VI");
    assert.deepEqual(received.future_provenance, { literal: "Scharff" });
  });
});
