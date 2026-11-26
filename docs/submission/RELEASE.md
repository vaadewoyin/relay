# Relay 0.1.0 release candidate

Relay brings an evidence-backed shift brief to Even G2. It reads Notion shift reports, presents locally validated Gemini proposals, and lets an incoming operator explicitly accept authorized work. The verified receipt and current owner can sync back to Notion. The verified demonstration uses synthetic data and the official simulator.

## Package and verification

- Package ID `com.relay.handover`, version `0.1.0`, Even Hub SDK `0.0.10`.
- Local package `artifacts/phase7a/release/relay-0.1.0.ehpk` (40,518 bytes).
- SHA-256 `0905a6fddf83110b3e241893e7e54213cc3dcde92ca6a06c39456bade81524d5`.
- The packer stamped minimum companion version `2.2.5` from its bundled SDK map. TypeScript, Vite build, and packaging passed. The package includes the three license notices.
- Physical G2 installation is unverified. This package has no configured phone-reachable API or network allowlist. Use the simulator setup for the verified workflow.

Use Node.js 22.12+ and npm. The lockfile selects CLI 0.1.14 and SDK 0.0.10.

```bash
cd frontend
npm ci
npm run pack
sha256sum out.ehpk
```

To check the staged submission copy, run from the repository root:

```bash
cd artifacts/phase7a/release
sha256sum -c SHA256SUMS
```

Use the [README quick start](../../README.md#quick-start) for the simulator. Even Hub Private Testing is the documented install route for an actual package on a paired phone. Follow that documentation after configuring a secure phone-reachable API, the app allowlist, trusted synthetic context, and CORS, and rebuild for that target. [Even Hub Private Testing](https://hub.evenrealities.com/docs/test/private-testing) · [Relay physical networking](../../frontend/README.md#simulator-and-physical-networking)

## Publish only with owner approval

1. Confirm that the release is authorized and select the verified final Phase 7A commit. In GitHub open **Releases → Draft a new release**, choose tag `v0.1.0` targeting that commit, and title it **Relay 0.1.0**.
2. Paste the summary and package limitations above. Link the setup README and the exported demo video. Attach `relay-0.1.0.ehpk` and `SHA256SUMS`. Keep the release a draft until the owner approves publication.
3. After publication, download both assets and check the checksum. A release is optional for the competition. Follow the organizer form if the package can be attached directly. [GitHub release guide](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
