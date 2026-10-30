# Verified backups and restore rehearsal

The backup tool preserves database rows, raw results, source bytes, review history and managed processing artifacts. It verifies recorded evidence hashes, creates a consistent SQLite/file snapshot, writes a transport manifest, actually extracts the archive into a disposable directory, and validates database schema/references/triggers and evidence before publishing the backup.

Run it with the locked Python environment. For a native data directory:

```bash
node scripts/dev/python.mjs scripts/graphics/backup.py create /path/to/data /path/outside-data/research-backup.zip
node scripts/dev/python.mjs scripts/graphics/backup.py verify /path/outside-data/research-backup.zip
node scripts/dev/python.mjs scripts/graphics/backup.py restore /path/outside-data/research-backup.zip /path/to/new-restored-data
```

`create` and `restore` refuse existing targets. A restore is staged, verified and atomically published without replacing another directory. The archive must be outside its source data directory. Temporary snapshot/extraction storage is required in addition to the final archive; insufficient space or failed verification leaves the final target unpublished. Keep backups outside Git and protect them like the original data: they may contain private images and reviewer identities.

## Live service coordination

The current service and backup tool share an operation lock. Backup waits for active OCR and excludes new mutations while taking the snapshot; `--timeout 60` controls the wait. SQLite write locking also protects the database snapshot from older services that do not cooperate with the file lock. Read-only responses can continue. A restore into an existing or live data directory is never allowed.

The report lists schema version, run/event counts, coverage and historically unverifiable files. A legacy OCR input/TSV without an original digest is preserved as transport-checked backup bytes, while its historical limitation remains explicit. Restoring a backup does not invent historical hashes or rewrite raw OCR. This differs from research ZIP exports, which omit unverifiable legacy processing files.

## Docker data

Build the current graphics image first; the historical 0.1.0 image does not contain this new tool. Inside a current graphics container the same commands are available as `python -m backups`. For the separate development stack:

```bash
scriptor_archive="scriptor-$(date +%Y%m%d-%H%M%S).zip"
scriptor_backup_dir="$PWD/release/backups"
mkdir -p "$scriptor_backup_dir"
npm run runtime -- exec -- docker compose -f compose.dev.yaml exec -T graphics python -m backups create /data "/tmp/$scriptor_archive"
npm run runtime -- exec -- docker compose -f compose.dev.yaml cp "graphics:/tmp/$scriptor_archive" "$scriptor_backup_dir/$scriptor_archive"
node scripts/dev/python.mjs scripts/graphics/backup.py verify "$scriptor_backup_dir/$scriptor_archive"
```

The current working image is `modavis-scriptor-graphics:development`. For a restore preview without touching the original volume, create a new explicitly named volume and restore into a new child directory:

```bash
scriptor_restore_volume="modavis-scriptor-restore-$(date +%Y%m%d-%H%M%S)"
npm run runtime -- exec -- docker volume create "$scriptor_restore_volume"
npm run runtime -- exec -- docker run --rm --user 0 \
  --mount "type=volume,source=$scriptor_restore_volume,target=/restore" \
  --entrypoint chown modavis-scriptor-graphics:development 10001:10001 /restore
npm run runtime -- exec -- docker run --rm \
  --mount "type=volume,source=$scriptor_restore_volume,target=/restore" \
  --mount "type=bind,source=$scriptor_backup_dir,target=/archives,readonly" \
  --entrypoint python modavis-scriptor-graphics:development \
  -m backups restore "/archives/$scriptor_archive" /restore/restored
```

The initialization command gives the new volume root to the image's unprivileged graphics user; restoration itself runs as that user. The target is `/restore/restored`, because the volume mount root already exists and non-overwriting restore deliberately refuses existing directories. A preview service can mount that new volume at `/data` and set `GRAPHICS_DATA=/data/restored`, on an unused loopback port. Keep its Compose project/name and ports separate from research and development services. Validate reads and review history before choosing a restored copy for continued work; retain the original and the archive.

The automated reliability suite rehearses live backup during a concurrent review, actual extraction/restore, corrupt archives, schema/trigger checks, traversal rejection, legacy byte preservation and refusal to overwrite targets. POSIX restores fsync files and nested directories before publication; Python does not expose equivalent directory fsync on Windows. Neither format is a signed archive against an administrator who can replace files and checksums together.
