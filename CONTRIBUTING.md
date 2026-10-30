# Contributing

Use a feature branch and include tests for behavioral changes. Run the checks documented in `README.md` before submitting a change. Never commit research credentials, private document sources, processing volumes or reviewer-identifying data.

Changes to recognition, retrieval or review behavior must preserve immutable raw OCR, document configuration and model versions, and explain their effect on provenance and reproducibility.

Use Node 22.23.4 from `.nvmrc`. Run `npm ci`, `npm run doctor`, `npm run check` and `npm run test:integration`; install Chromium with `npx playwright install chromium` before the integration run. Tests use a randomly named disposable Compose project and free loopback ports. Never point mutation tests at research services or attach a research volume to the test stack.

Keep historical fixture results and their source snapshots unchanged when changing the current implementation. Add regression cases for changed behavior. Schema changes need an ordered migration and an upgrade test preserving existing runs, events and integrity constraints. The current schema is versioned with SQLite `PRAGMA user_version`.

The next milestone and evaluation prerequisites are in `docs/ROADMAP.md` and `docs/EVALUATION.md`. Record new recognition results with the configuration, dataset split, source digests and metric denominator; do not present the tuned example as held-out evidence.
