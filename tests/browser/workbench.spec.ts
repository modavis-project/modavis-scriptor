import { readFile } from "node:fs/promises";
import { expect, test, type APIRequestContext } from "@playwright/test";

const seed = "example-organ-stops-v1";
const endpoint = (id: string) => `/api/graphics/runs/${id}`;

async function disposableRun(request: APIRequestContext) {
  const health = await request.get("/api/graphics/health", { maxRedirects: 0 });
  expect(health.ok()).toBe(true);
  expect((await health.json()).disposable_test_instance).toBe(true);
  const baseline = await request.get(endpoint(seed), { maxRedirects: 0 });
  expect(baseline.ok()).toBe(true);
  expect((await baseline.json()).result.review_events).toEqual([]);
  // Each browser gets a distinct child: the shared example is never reviewed.
  const created = await request.post(`${endpoint(seed)}/rerun`, { data: {}, maxRedirects: 0 });
  expect(created.status()).toBe(202);
  const id: string = (await created.json()).id;
  expect(id).not.toBe(seed);
  let completed;
  await expect.poll(async () => {
    const response = await request.get(endpoint(id), { maxRedirects: 0 });
    expect(response.ok()).toBe(true);
    completed = await response.json();
    expect(completed.run.status).not.toBe("failed");
    return completed.run.status;
  }, { timeout: 90_000, intervals: [200, 500, 1000] }).toBe("completed");
  return { id, result: completed!.result };
}

test("isolated evidence review, keyboard drafts, conflicts, persistence and responsive exports", async ({ page, request }, testInfo) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const { id, result: initial } = await disposableRun(request);
  expect(initial.regions).toHaveLength(21);
  expect(initial.regions[2].raw_text).toBe("Scharff\nIV-VI");
  await page.goto(`/graphics?run=${id}`);
  await expect(page.getByRole("heading", { name: "Grafiken & Registerzüge" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Region \d+:/ })).toHaveCount(21);
  const select = async (number: number) => {
    const button = page.getByRole("button", { name: new RegExp(`^Region ${number}:`) });
    await button.focus();
    await button.press("Enter");
    await expect(button).toHaveAttribute("aria-pressed", "true");
  };
  await select(3);
  const review = page.getByRole("region", { name: "Prüfung Region 3", exact: true });
  const reading = review.getByRole("textbox", { name: "Lesung / Name", exact: true });
  const rationale = review.getByRole("textbox", { name: "Begründung anhand des Bildes", exact: true });
  await expect(review.getByRole("img", { name: "Unveränderter Bildausschnitt, Region 3" })).toBeVisible();
  await expect(reading).toHaveValue("Scharff");
  await reading.focus();
  await reading.press("Tab");
  await expect(review.getByRole("textbox", { name: "Angabe wörtlich (z. B. IV–VI)", exact: true })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(reading).toBeFocused();
  const candidate = review.locator("details").filter({ has: page.getByText("Scharf", { exact: true }) });
  await candidate.locator("summary").click();
  await candidate.getByRole("button", { name: "Name als Entwurf übernehmen" }).click();
  await expect(reading).toHaveValue("Scharf");
  const draftResponse = await request.get(endpoint(id));
  const draftState = (await draftResponse.json()).result;
  expect(draftState.review_events).toEqual([]);
  expect(draftState.regions[2].effective.name).toBe("Scharff");

  const accept = review.getByRole("button", { name: "Lesung freigeben" });
  await expect(accept).toBeDisabled();
  await review.getByRole("textbox", { name: "Prüfer/in", exact: true }).fill(`Browser QA ${testInfo.project.name}`);
  await expect(accept).toBeDisabled();
  await rationale.fill("short");
  await expect(rationale).toHaveValue("short");
  await expect(accept).toBeDisabled();
  const reason = "TEST ONLY: checking visible spelling and explicit human acceptance.";
  await rationale.fill(reason);
  await expect(accept).toBeEnabled();
  // Navigating with a keyboard must retain the unsaved reading and rationale.
  await select(4);
  await expect(page.getByRole("region", { name: "Prüfung Region 4", exact: true })).toBeVisible();
  await select(3);
  await expect(reading).toHaveValue("Scharf");
  await expect(rationale).toHaveValue(reason);
  const saved = page.waitForResponse((response) => response.url().endsWith("/regions/r003/review") && response.request().method() === "PATCH");
  await accept.click();
  expect((await saved).ok()).toBe(true);
  await expect(review).toContainText("Freigegeben · v1");
  const working = page.getByRole("article", { name: "Vollständiger Arbeitsstand der Bildauswertung" });
  await expect(working.getByRole("cell", { name: "Scharf", exact: true })).toBeVisible();
  await page.reload();
  await select(3);
  await expect(review).toContainText("Freigegeben · v1");
  await expect(reading).toHaveValue("Scharf");
  await page.getByRole("tab", { name: "Unveränderte OCR", exact: true }).click();
  await expect(page.getByRole("article", { name: "Vollständige unveränderte Bild-OCR" })).toContainText("Scharff");
  await page.getByRole("tab", { name: "Unveränderte OCR", exact: true }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("tab", { name: "Arbeitsstand", exact: true })).toBeFocused();
  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "JSON", exact: true }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe(`${id}.json`);
  const downloaded = await download.path();
  expect(downloaded).not.toBeNull();
  const exported = JSON.parse(await readFile(downloaded!, "utf8"));
  expect(exported.regions[2].effective.name).toBe("Scharf");
  expect(exported.regions[2].raw_text).toBe(initial.regions[2].raw_text);
  expect(exported.immutable_result_sha256).toBe(initial.immutable_result_sha256);
  expect(exported.review_events).toHaveLength(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await select(4);
  const other = page.getByRole("region", { name: "Prüfung Region 4", exact: true });
  await expect(other.getByRole("textbox", { name: "Lesung / Name", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await testInfo.attach("mobile-review", { body: await page.screenshot(), contentType: "image/png" });
  await page.setViewportSize({ width: 1920, height: 1080 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);

  // Another reviewer commits while this browser still holds version zero.
  const staleName = "Unsaved browser reading";
  const staleReason = "TEST ONLY: this draft must survive a concurrent review conflict.";
  await other.getByRole("textbox", { name: "Lesung / Name", exact: true }).fill(staleName);
  await other.getByRole("textbox", { name: "Prüfer/in", exact: true }).fill("Browser conflict QA");
  await other.getByRole("textbox", { name: "Begründung anhand des Bildes", exact: true }).fill(staleReason);
  const concurrent = await request.patch(`${endpoint(id)}/regions/r004/review`, { data: {
    action: "accept", reviewer: "Parallel reviewer QA", rationale: "TEST ONLY: concurrent human review must not be silently overwritten.",
    name: "Parallel accepted reading", specification: initial.regions[3].parsed.specification,
    kind: initial.regions[3].parsed.kind, division: "", expected_version: 0,
  } });
  expect(concurrent.ok()).toBe(true);
  const conflicting = page.waitForResponse((response) => response.url().endsWith("/regions/r004/review") && response.request().method() === "PATCH");
  await other.getByRole("button", { name: "Lesung freigeben" }).click();
  expect((await conflicting).status()).toBe(409);
  await expect(page.getByRole("alert")).toContainText(/Review changed|409/);
  await expect(other.getByRole("textbox", { name: "Lesung / Name", exact: true })).toHaveValue(staleName);
  await expect(other.getByRole("textbox", { name: "Begründung anhand des Bildes", exact: true })).toHaveValue(staleReason);
  const afterConflict = (await (await request.get(endpoint(id))).json()).result;
  expect(afterConflict.regions[3].effective.name).toBe("Parallel accepted reading");
  expect(afterConflict.review_events).toHaveLength(2);
  await page.getByRole("button", { name: "Erneut laden", exact: true }).click();
  await expect(other.getByRole("status")).toContainText("Eine neuere Entscheidung liegt vor");
  await expect(other.getByRole("textbox", { name: "Lesung / Name", exact: true })).toHaveValue(staleName);
  await expect(other.getByRole("textbox", { name: "Begründung anhand des Bildes", exact: true })).toHaveValue(staleReason);
  await other.getByRole("button", { name: "Nach Vergleich auf aktuelle Version beziehen", exact: true }).click();
  expect((await (await request.get(endpoint(id))).json()).result.review_events).toHaveLength(2);
  const resolved = page.waitForResponse((response) => response.url().endsWith("/regions/r004/review") && response.request().method() === "PATCH");
  await other.getByRole("button", { name: "Lesung freigeben" }).click();
  expect((await resolved).ok()).toBe(true);
  await expect(other).toContainText("Freigegeben · v2");
  const afterResolution = (await (await request.get(endpoint(id))).json()).result;
  expect(afterResolution.review_events).toHaveLength(3);
  expect(afterResolution.immutable_result_sha256).toBe(initial.immutable_result_sha256);
  await page.reload();
  await select(4);
  await expect(other.getByRole("textbox", { name: "Lesung / Name", exact: true })).toHaveValue(staleName);
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect((await (await request.get(endpoint(seed))).json()).result.review_events).toEqual([]);
  expect(pageErrors).toEqual([]);
});
