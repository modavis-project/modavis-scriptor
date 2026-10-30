import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("evidence review keeps drafts separate, persists acceptance, and exports literal OCR", async ({ page, request }) => {
  const healthResponse = await request.get("/api/graphics/health", { maxRedirects: 0 });
  expect(healthResponse.ok()).toBe(true);
  expect((await healthResponse.json()).disposable_test_instance).toBe(true);
  const initialResponse = await request.get("/api/graphics/runs/example-organ-stops-v1", { maxRedirects: 0 });
  expect(initialResponse.ok()).toBe(true);
  const initial = (await initialResponse.json()).result;
  expect(initial.review_events).toEqual([]);
  expect(initial.regions).toHaveLength(21);
  expect(initial.regions[2].raw_text).toBe("Scharff\nIV-VI");

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Grafiken & Registerzüge" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Region \d+:/ })).toHaveCount(21);
  await page.getByRole("button", { name: /^Region 3:/ }).click();
  const review = page.getByRole("region", { name: "Prüfung Region 3", exact: true });
  await expect(review.getByRole("img", { name: "Unveränderter Bildausschnitt, Region 3" })).toBeVisible();
  await expect(review.getByLabel("Lesung / Name", { exact: true })).toHaveValue("Scharff");

  const candidate = review.locator("details").filter({ has: page.getByText("Scharf", { exact: true }) });
  await candidate.locator("summary").click();
  await candidate.getByRole("button", { name: "Name als Entwurf übernehmen" }).click();
  await expect(review.getByLabel("Lesung / Name", { exact: true })).toHaveValue("Scharf");
  const unchanged = await request.get("/api/graphics/runs/example-organ-stops-v1");
  const draftState = (await unchanged.json()).result;
  expect(draftState.review_events).toEqual([]);
  expect(draftState.regions[2].effective.name).toBe("Scharff");

  const accept = review.getByRole("button", { name: "Lesung freigeben" });
  await expect(accept).toBeDisabled();
  await review.getByLabel("Prüfer/in", { exact: true }).fill("Browser QA");
  await expect(accept).toBeDisabled();
  const rationale = review.getByRole("textbox", { name: "Begründung anhand des Bildes", exact: true });
  await rationale.fill("short");
  await expect(rationale).toHaveValue("short");
  await expect(accept).toBeDisabled();
  await rationale.fill("TEST ONLY: checking visible spelling and explicit human acceptance.");
  await expect(accept).toBeEnabled();
  const saved = page.waitForResponse((response) => response.url().endsWith("/regions/r003/review") && response.request().method() === "PATCH");
  await accept.click();
  expect((await saved).ok()).toBe(true);
  await expect(review).toContainText("Freigegeben · v1");
  const working = page.getByRole("article", { name: "Vollständiger Arbeitsstand der Bildauswertung" });
  await expect(working.getByRole("cell", { name: "Scharf", exact: true })).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: /^Region 3:/ }).click();
  await expect(review).toContainText("Freigegeben · v1");
  await expect(review.getByLabel("Lesung / Name", { exact: true })).toHaveValue("Scharf");
  await expect(working.getByRole("cell", { name: "Scharf", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Unveränderte OCR", exact: true }).click();
  await expect(page.getByRole("article", { name: "Vollständige unveränderte Bild-OCR" })).toContainText("Scharff");

  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "JSON", exact: true }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe("example-organ-stops-v1.json");
  const downloadPath = await download.path();
  expect(downloadPath).not.toBeNull();
  const exported = JSON.parse(await readFile(downloadPath!, "utf8"));
  expect(exported.regions[2].effective.name).toBe("Scharf");
  expect(exported.regions[2].raw_text).toBe(initial.regions[2].raw_text);
  expect(exported.immutable_result_sha256).toBe(initial.immutable_result_sha256);
  expect(exported.review_events).toHaveLength(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: /^Region 3:/ }).click();
  await expect(review.getByRole("heading", { name: "Region 3", exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
