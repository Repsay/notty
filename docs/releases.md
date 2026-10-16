# Publishing releases

HACS uses published GitHub release tags as integration versions. The standard
GitHub source archive already contains `custom_components/notty`; no separate
ZIP asset or `zip_release` configuration is needed.

For each release:

1. Update `custom_components/notty/manifest.json` and `pyproject.toml` to the same
   new version, then run `uv lock` to update the project entry in `uv.lock`.
2. Add `release-notes/vVERSION.md`, including migration or automation changes
   and the limits of live validation. Merge the version and notes through a PR.
3. Tag that merged commit and push the tag. For example, for the next patch:

   ```sh
   git fetch origin
   git tag -a v0.3.1 origin/main -m "NOTTY v0.3.1"
   git push origin v0.3.1
   ```

The Release workflow runs the shared test, Ruff, mypy, HACS and Hassfest checks
on the tagged commit. Publishing requires all jobs to succeed, a stable
`vMAJOR.MINOR.PATCH` tag matching both version files, and nonempty notes for that
tag. It then creates the GitHub release and marks it latest. Branch pushes alone
do not publish updates. Tags/releases are not automatically moved or overwritten.

If checks fail, repair and release a new version; do not silently replace a
published version. If publishing alone fails after validation, fix the access or
service problem and rerun the failed job for the original tag.

Users need to install the integration through HACS and track a numbered release
to receive release updates. After updating, restart Home Assistant. Manual copies
and installations pinned to the default branch may need an initial HACS download
of a numbered release. See the [HACS integration release documentation](https://www.hacs.dev/docs/publish/integration/#github-releases-optional).
