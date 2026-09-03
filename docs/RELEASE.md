# Release procedure

## Repository checks

1. Update `package.json`, `CITATION.cff`, `.zenodo.json`, API version, image tags and changelog consistently.
2. Run lint, TypeScript, production build, Compose validation and isolated API tests.
3. Verify the example file manifest and corpus checksum.
4. Inspect the Git index for private sources, credentials, local data volumes, temporary files and oversized artifacts.
5. Commit the release and create the annotated version tag.

No private manuscript collection is part of the release tree or history.

## Archive

Create the source archive from the release tag, not from the working directory:

```bash
git archive --format=zip --prefix=modavis-scriptor-0.1.0/ \
  --output=modavis-scriptor-0.1.0.zip v0.1.0
```

Calculate a SHA-256 for local archival fixity and compare the uploaded MD5 with the local MD5 returned by Zenodo. Keep the version, commit, tag object, archive size and digests in the release record.

## Zenodo draft

The release record is reserved at <https://doi.org/10.5281/zenodo.22284008>. Metadata is maintained in `.zenodo.json`; citation data is in `CITATION.cff`.

Uploading a source archive and updating metadata must not publish the draft. Verify that the target record is the expected unsubmitted draft before every write and recheck its `submitted` state afterwards. Use `ZENODO_API_KEY` only as an environment variable and send it in an HTTPS `Authorization` header, never in a URL, Git configuration or committed file.

The project owner decides when the GitHub repository becomes public and when the Zenodo record is published. Repository visibility and Zenodo publication are separate actions.
