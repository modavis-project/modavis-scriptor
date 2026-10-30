# Working on MODAVIS Scriptor

Work in this repository, not the sibling `scriptorium-workbench` prototype. Use the exact Node version in `.nvmrc`; `docs/INSTALLATION.md` describes a pinned npm-exec alternative to a version manager.

Run `npm run doctor`, `npm run check`, `npm run contracts:check`, `npm run test:contracts`, `npm run test:dev`, `npm run test:evaluation` and `npm run test:integration` for behavioral changes. Contract generation/workflow previews need the locked Python environment. The integration runner builds a disposable stack with its own project name, data and free loopback ports. Optional native validation is `npm run test:integration -- --native` after `scripts/dev/setup-native.py` and the native prerequisites.

On this Mac, use `npm run runtime -- exec -- npm run test:integration` for Scriptor's dedicated internal-APFS Docker context. The helper does not switch the global Docker context or move other projects. Details are in `docs/DEVELOPMENT.md`.

Never point mutation tests at research services or mount their data volumes in tests. Use `compose.dev.yaml` for separate backend development data and the native web process for frontend reload; `compose.yaml` is the research deployment. Existing local services may occupy ports 3000/8010 or 3080/8080.

Keep raw OCR, original evidence, historical fixture results and their source snapshots unchanged. Corpus retrieval stays advisory; human acceptance needs reviewer, rationale and version. New artifacts need manifest coverage, and schema changes need an ordered migration plus preservation/recovery tests. Tests must use temporary data and reject unverifiable evidence rather than resetting its checksum.

Edit Pydantic contracts in `services/graphics/contracts.py` and regenerate committed frontend types/schema; never hand-edit generated contracts. Review drafts and explicit conflict resolution must survive UI changes. Processing publication/recovery, backup/restore and bounded-memory transfers have dedicated reliability regressions.

Read `docs/ROADMAP.md` for the next milestone and `docs/EVALUATION.md` before recognition-quality work. The tuned example and synthetic scorer tests do not establish general OCR accuracy.

The user requested an unreviewed candidate set and annotation workflow. Keep actual candidate annotations/completions absent unless genuine reviewers supply them. Do not fabricate independent human readings or benchmark scores. Annotation data and downloaded images stay in ignored `evaluation-data/`; only rights-documented public candidate metadata belongs in Git.
