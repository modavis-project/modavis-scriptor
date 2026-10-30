# Working on MODAVIS Scriptor

Work in this repository, not the sibling `scriptorium-workbench` prototype. Use the exact Node version in `.nvmrc`; `docs/INSTALLATION.md` describes a pinned npm-exec alternative to a version manager.

Run `npm run doctor`, `npm run check`, `npm run test:evaluation` and `npm run test:integration` for behavioral changes. The integration runner builds a disposable stack with its own project name, data and free loopback ports. Optional native validation is `npm run test:integration -- --native` after `scripts/dev/setup-native.py` and the native prerequisites.

Never point mutation tests at research services or mount their data volumes in tests. Use `compose.dev.yaml` for separate backend development data and the native web process for frontend reload; `compose.yaml` is the research deployment. Existing local services may occupy ports 3000/8010 or 3080/8080.

Keep raw OCR, original evidence, historical fixture results and their source snapshots unchanged. Corpus retrieval stays advisory; human acceptance needs reviewer, rationale and version. New artifacts need manifest coverage, and schema changes need an ordered migration plus preservation/recovery tests. Tests must use temporary data and reject unverifiable evidence rather than resetting its checksum.

Read `docs/ROADMAP.md` for the next milestone and `docs/EVALUATION.md` before recognition-quality work. The tuned example and synthetic scorer tests do not establish general OCR accuracy.
