# Portal copy

**Project:** Relay

**Tagline:** Nothing gets lost between shifts.

**Track:** 04 — AI Assistants & Work

**One sentence:** Relay gives incoming maintenance operators an evidence-backed shift brief on Even G2 and writes verified ownership decisions back to Notion.

## Short description

Maintenance teams often hand over open work across checklists, messages, and reports. When two people describe the same equipment test differently, the incoming operator has to search for context while standing at the equipment. Relay brings that decision to Even G2. It reads original shift reports from Notion and uses Gemini to propose meaningful contradictions. Relay checks that the cited excerpts exist, then shows both accounts on the glasses for human review. The operator can acknowledge the finding and separately confirm responsibility for eligible work. Relay creates a persistent receipt, publishes it to Notion, and updates the current owner in the Action Register. Relay targets facilities maintenance, hospitality operations, and other shift-based teams. It was built for Track 04, AI Assistants & Work, and verified with synthetic data in the official Even Hub simulator.

## Detailed fields

- **Intended users** are incoming and outgoing facilities maintenance operators, hospitality operations teams, and similar shift-based teams.
- **Problem and solution** are fragmented shift reports and ambiguous ownership. Relay prioritizes the decision, shows the two original accounts, and records who actually accepts work.
- **Why G2** is useful at the equipment. The brief, source comparison, and acceptance fit short, glanceable views. Gestures let the operator progress without opening a phone and searching through multiple pages.
- **Read/write and Notion** include importing actual report pages, showing their immutable excerpts, publishing a verified receipt, and updating the stable Action Register owner with an audit event.
- **Technical innovation** combines structured Gemini proposals with deterministic evidence validation, a separate operator confirmation, transactional acceptance, and durable publication tracking.
- **AI capabilities and safeguards** include semantic contradiction proposals and verifiable citations. Operators decide what the evidence means. The model never receives authority to transfer ownership.
- **Business potential** is a pilot with teams already using a shared work register. Measure time to locate critical context, handovers with a confirmed owner, and unresolved items carried to the next shift. No pilot outcomes have been measured.
- **Current limitations** are synthetic data, verification on the official simulator, deferred voice, unverified physical installation, and a trusted loopback API for the demo. Shared deployment needs authenticated identities, record authorization, secure connectivity, and operator conflict handling.
