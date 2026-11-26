# Public repository checklist

Audited against the Phase 5 published baseline and the Phase 6 changes. The repository remains private.

- [x] Check the staged paths, tracked files, and published Git diffs for recognizable provider keys, private keys, real workspace IDs, and user home paths. The scan found no matches for the configured private values or credential patterns. This is a targeted scan and does not rule out every kind of secret.
- [x] Keep `.env`, SQLite databases, dependency directories, generated packages, logs, and demo screenshots out of Git. `backend/.env.example` carries names only.
- [x] Inventory Git history size. The largest historical blob at the Phase 5 baseline was 75,756 bytes. No historical blob exceeded 1 MiB.
- [x] Review reproducible startup, Python and npm lockfiles, environment setup, and the actual provider, simulator, and physical-device limitations.
- [ ] Review Git author and committer metadata before publication. History contains one distinct non-noreply email value. Choose whether that metadata may be public. Avoid rewriting existing history without explicit authorization.
- [ ] Decide how to license the repository's original code. The existing MIT notice in `frontend/LICENSE` covers the attributed Even Realities starter. Relay's original backend has no explicit repository-wide license grant. Preserve the upstream notice.
- [ ] Check exported submission footage and screenshots for private workspace IDs, names, and browser chrome. Local verification artifacts may contain synthetic-workspace IDs or URLs. Use the simulator captures and review them before external sharing.
- [ ] Confirm the organizer's repository requirements and obtain the owner's approval before changing visibility.

The demo API is intentionally loopback-only and uses synthetic data. Shared deployment would require authenticated identity, record-level authorization, HTTPS, and an explicit phone WebView origin and Even Hub network allowlist.
