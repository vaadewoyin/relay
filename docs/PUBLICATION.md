# Public repository checklist

Phase 7A reviewed the worktree, repository history, public stills, package build inputs, and submission kit. The owner controls repository visibility, release publication, and entry submission.

- [x] Scan for configured provider tokens and workspace identifiers, normalized Notion IDs, recognizable secret patterns, private Notion links, and developer paths. No matches in the inspected history, proposed files, or WebView build inputs. The scan is targeted. It cannot establish the absence of every possible secret.
- [x] Confirm that `.env`, dependencies, SQLite files, compiled output, and the generated package stay ignored. The only checked-in environment file is the names-only `backend/.env.example`.
- [x] Review history size. The largest inspected blob was 75,756 bytes. No blob exceeded 1 MiB.
- [x] Visually inspect the four checked-in synthetic simulator frames. They show no private workspace or receipt identifiers. Keep the fuller local simulator and Notion captures private.
- [x] Preserve the upstream starter notice, add Relay's [MIT license](../LICENSE), and ship the [upstream notices](submission/LICENSES.md) with the web package.
- [x] Document locked offline and live setup, the local trust boundary, and the physical-device and voice limitations.
- [ ] Decide whether to expose historical Git metadata. The existing history contains one distinct non-noreply author or committer email. Making this history public exposes the address. A noreply setting for future commits would leave past commits as published. Keep history intact unless the owner explicitly authorizes a change.
- [ ] Review the final exported video frame by frame for private data. Mask IDs on the evidence and receipt screens and capture only the approved synthetic Notion fields. Exclude account chrome, bookmarks, private URLs, terminals, and Swagger responses. Confirm the narration contains no private identifiers.
- [ ] After approval, make the repository public and check the README and license links signed out. Keep the package and checksum local until the owner approves attaching them or publishing a GitHub release.

The API uses synthetic demo identities on loopback. Shared deployment needs authenticated identity, record-level authorization, HTTPS, an explicit phone WebView origin, and an Even Hub network allowlist.
