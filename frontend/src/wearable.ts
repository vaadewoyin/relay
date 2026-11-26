import { ApiError } from './api.ts'
import type { Finding, Handover, PreviewCommand, Receipt, RelayApi, ReviewCommand } from './api.ts'
import type { ShiftContext } from './shift-context.ts'
import { memoryJournal } from './transfer-journal.ts'
import type { PendingTransfer, TransferJournal } from './transfer-journal.ts'
import { clip, display, evidencePages, excerpt, findingTitles, itemPages, menu, orderFindings, tagline, wrapText } from './view.ts'
import type { EvidencePage } from './view.ts'

export type Gesture = 'up' | 'down' | 'tap' | 'back'

type Brief = { kind: 'brief'; cursor: number }
type Queue = { kind: 'queue'; cursor: number }
type Detail = { kind: 'detail'; finding: Finding; cursor: number; queueIndex: number }
type Preview = { kind: 'preview'; handover: Handover; cursor: number }
type Failure = {
  kind: 'error'; title: string; message: string; retry: () => Promise<void>; back?: Screen
}
type Screen =
  | Brief | Queue | Detail | Preview
  | { kind: 'confirm'; preview: Preview; cursor: number }
  | { kind: 'receipt'; receipt: Receipt; cursor: number }
  | { kind: 'evidence'; pages: EvidencePage[]; cursor: number; back: Detail }
  | { kind: 'review'; detail: Detail; cursor: number }
  | { kind: 'notes'; detail: Detail; lines: string[]; cursor: number }
  | { kind: 'loading'; message: string }
  | Failure
  | { kind: 'configuration' }

const queueSize = 4
const move = (cursor: number, length: number, direction: number) =>
  Math.max(0, Math.min(cursor + direction, length - 1))
const brief = (): Brief => ({ kind: 'brief', cursor: 0 })

export class Wearable {
  private readonly api: RelayApi
  private readonly context: ShiftContext | undefined
  private readonly draw: (content: string) => Promise<void>
  private readonly exit: () => Promise<void>
  private readonly clock: () => number
  private readonly operationId: () => string
  private readonly journal: TransferJournal
  private screen: Screen = { kind: 'loading', message: 'Connecting to Relay...' }
  private findings: Finding[] = []
  private findingsLoaded = false
  private busy = false
  private lastTap = -Infinity
  private receiptId?: string

  constructor(options: {
    api: RelayApi
    context?: ShiftContext
    draw: (content: string) => Promise<void>
    exit: () => Promise<void>
    clock?: () => number
    operationId?: () => string
    journal?: TransferJournal
  }) {
    this.api = options.api
    this.context = options.context
    this.draw = options.draw
    this.exit = options.exit
    this.clock = options.clock ?? (() => performance.now())
    this.operationId = options.operationId ?? (() => crypto.randomUUID())
    this.journal = options.journal ?? memoryJournal()
  }

  async start() {
    this.busy = true
    try {
      if (!this.context) await this.show({ kind: 'configuration' })
      else await this.resume()
    } finally {
      this.busy = false
    }
  }

  async input(gesture: Gesture): Promise<void> {
    if (this.busy) return
    if (gesture === 'tap') {
      const now = this.clock()
      if (now - this.lastTap < 350) return
      this.lastTap = now
    }
    this.busy = true
    try {
      const current = this.screen
      if (gesture === 'back') {
        await this.back(current)
      } else if (gesture === 'tap') {
        await this.tap(current)
      } else if ('cursor' in current) {
        await this.scroll(current, gesture === 'up' ? -1 : 1)
      }
    } finally {
      this.busy = false
    }
  }

  private async scroll(current: Extract<Screen, { cursor: number }>, direction: number) {
    const lengths = {
      brief: 3,
      queue: this.findings.length,
      detail: current.kind === 'detail' && current.finding.review_status === 'pending' ? 3 : 2,
      evidence: current.kind === 'evidence' ? current.pages.length : 0,
      review: 3,
      notes: current.kind === 'notes' ? Math.ceil(current.lines.length / 6) : 0,
      preview: current.kind === 'preview' ? itemPages(current.handover.actions).length : 0,
      confirm: 2,
      receipt: current.kind === 'receipt'
        ? itemPages([...current.receipt.transferred, ...current.receipt.outstanding]).length : 0,
    }
    const cursor = move(current.cursor, lengths[current.kind], direction)
    if (cursor !== current.cursor) await this.show({ ...current, cursor })
  }

  private async back(current: Screen) {
    switch (current.kind) {
      case 'brief':
      case 'configuration':
        await this.exit()
        break
      case 'queue':
      case 'preview':
        await this.show(brief())
        break
      case 'receipt':
        if (this.findingsLoaded) await this.show(brief())
        else await this.refresh()
        break
      case 'confirm':
        await this.show(current.preview)
        break
      case 'detail':
        await this.show({ kind: 'queue', cursor: current.queueIndex })
        break
      case 'evidence':
        await this.show(current.back)
        break
      case 'notes':
      case 'review':
        await this.show(current.detail)
        break
      case 'error':
        if (current.back) await this.show(current.back)
        else await this.exit()
        break
    }
  }

  private async tap(current: Screen) {
    switch (current.kind) {
      case 'brief':
        if (current.cursor === 0) await this.show({ kind: 'queue', cursor: 0 })
        else if (current.cursor === 1) {
          if (this.receiptId) await this.openReceipt(this.receiptId)
          else await this.openPreview()
        }
        else await this.refresh(current)
        break
      case 'queue': {
        const selected = this.findings[current.cursor]
        if (!selected) break
        const load = async () => {
          const finding = await this.api.finding(selected.id)
          if (finding.id !== selected.id) throw new ApiError('invalid_response', 'Finding ID changed.')
          await this.show({ kind: 'detail', finding, cursor: 0, queueIndex: current.cursor })
        }
        await this.request(load, 'Opening finding...', current)
        break
      }
      case 'detail':
        if (current.cursor === 0) await this.openEvidence(current)
        else if (current.cursor === 1 && current.finding.review_status === 'pending') {
          await this.show({ kind: 'review', detail: current, cursor: 0 })
        } else {
          const finding = current.finding
          const lines = [
            ...wrapText(finding.explanation),
            ...(finding.uncertainty ? wrapText('Uncertainty: ' + finding.uncertainty) : []),
            ...wrapText('Suggested review: ' + finding.recommended_action),
          ]
          await this.show({ kind: 'notes', detail: current, lines, cursor: 0 })
        }
        break
      case 'evidence':
        if (current.back.finding.review_status === 'pending') {
          await this.show({ kind: 'review', detail: current.back, cursor: 0 })
        }
        break
      case 'review':
        if (current.cursor === 0) await this.show(current.detail)
        else await this.review(current.detail, current.cursor === 1 ? 'confirmed' : 'dismissed')
        break
      case 'preview':
        if (current.handover.actions.some(item => item.transferable)) {
          await this.show({ kind: 'confirm', preview: current, cursor: 0 })
        }
        break
      case 'confirm':
        if (current.cursor === 0) await this.show(current.preview)
        else if (this.context) {
          await this.submitTransfer({
            kind: 'pending', handoverId: current.preview.handover.id,
            command: {
              operation_id: this.operationId(), actor_id: this.context.incomingOperatorId,
              expected_version: current.preview.handover.version, confirmed: true,
            },
          })
        }
        break
      case 'error':
        await current.retry()
        break
    }
  }

  private async resume() {
    let entry
    try {
      entry = this.journal.read()
    } catch {
      await this.show({
        kind: 'error', title: 'Transfer state unavailable',
        message: 'Relay cannot check saved transfer state. Restore local storage before continuing.',
        retry: () => this.resume(),
      })
      return
    }
    if (entry?.kind === 'pending') {
      await this.show(this.unverifiedTransfer(entry, 'Transfer status unknown'))
      return
    }
    this.receiptId = entry?.receiptId
    await this.refresh()
  }

  private async refresh(back?: Screen) {
    await this.request(async () => {
      await this.api.health()
      this.findings = orderFindings(await this.api.findings())
      this.findingsLoaded = true
      await this.show(brief())
    }, 'Connecting to Relay...', back)
  }

  private async openEvidence(detail: Detail) {
    await this.request(async () => {
      const references = detail.finding.evidence
      const pages: EvidencePage[] = []
      for (const [index, reference] of references.entries()) {
        const { report } = await this.api.report(reference.report_id)
        if (report.id !== reference.report_id || report.source_ref !== reference.source_ref
          || !report.text.includes(reference.quote)) {
          throw new ApiError('invalid_response', 'Evidence does not match the source report.')
        }
        pages.push(...evidencePages(report, index, references.length, reference.quote))
      }
      await this.show({ kind: 'evidence', pages, cursor: 0, back: detail })
    }, 'Checking source evidence...', detail)
  }

  private async openPreview() {
    const context = this.context
    if (!context) return
    const command: PreviewCommand = {
      operation_id: this.operationId(),
      actor_id: context.outgoingOperatorId,
      outgoing_shift_id: context.outgoingShiftId,
      incoming_shift_id: context.incomingShiftId,
    }
    await this.request(async () => {
      const handover = await this.api.preview(command)
      if (handover.status !== 'previewed' || handover.outgoing_shift_id !== command.outgoing_shift_id
        || handover.incoming_shift_id !== command.incoming_shift_id
        || handover.outgoing_operator_id !== command.actor_id
        || handover.incoming_operator_id !== context.incomingOperatorId) {
        throw new ApiError('invalid_response', 'Preview does not match the configured shifts.')
      }
      await this.show({ kind: 'preview', handover, cursor: 0 })
    }, 'Preparing handover...', brief())
  }

  private unverifiedTransfer(entry: PendingTransfer, title: string): Failure {
    return {
      kind: 'error', title,
      message: 'No receipt verified. Retry the same confirmed transfer.',
      retry: () => this.submitTransfer(entry),
    }
  }

  private async submitTransfer(entry: PendingTransfer) {
    const rejectedCodes = ['stale_version', 'handover_already_accepted', 'no_transferable_actions',
      'not_found', 'forbidden', 'invalid_operation', 'operation_id_reused']
    await this.request(async () => {
      try {
        this.journal.write(entry)
      } catch {
        throw new ApiError('storage', 'Could not save the transfer for safe retry.')
      }
      let accepted: Receipt
      try {
        accepted = await this.api.accept(entry.handoverId, entry.command)
      } catch (error) {
        if (error instanceof ApiError && rejectedCodes.includes(error.code)) this.journal.write()
        throw error
      }
      if (accepted.handover_id !== entry.handoverId) {
        throw new ApiError('invalid_response', 'Receipt is for a different handover.')
      }
      let receipt: Receipt
      try {
        receipt = await this.fetchReceipt(accepted.id, entry.handoverId)
      } catch {
        throw new ApiError('receipt_unverified', 'Could not read the stored receipt.')
      }
      this.journal.write({ kind: 'receipt', receiptId: receipt.id })
      this.receiptId = receipt.id
      await this.show({ kind: 'receipt', receipt, cursor: 0 })
    }, 'Verifying transfer receipt...', undefined, (error) => {
      if (error.code === 'stale_version') {
        return {
          title: 'Preview changed', message: 'Transfer rejected. Open and review a fresh preview.',
          retry: () => this.openPreview(), back: brief(),
        }
      }
      if (rejectedCodes.includes(error.code)) {
        return {
          title: 'Transfer rejected', message: error.message,
          retry: () => this.refresh(brief()), back: brief(),
        }
      }
      if (error.code === 'storage') {
        return {
          title: 'Transfer storage unavailable', message: error.message,
          retry: () => this.submitTransfer(entry),
        }
      }
      return this.unverifiedTransfer(entry, 'Transfer status unknown')
    })
  }

  private async fetchReceipt(id: string, handoverId?: string): Promise<Receipt> {
    const receipt = await this.api.receipt(id)
    if (receipt.id !== id || (handoverId && receipt.handover_id !== handoverId)
      || receipt.accepted_by !== this.context?.incomingOperatorId
      || receipt.incoming_shift_id !== this.context.incomingShiftId
      || receipt.outgoing_shift_id !== this.context.outgoingShiftId) {
      throw new ApiError('invalid_response', 'Receipt does not match this shift transfer.')
    }
    return receipt
  }

  private async openReceipt(id: string) {
    await this.request(async () => {
      const receipt = await this.fetchReceipt(id)
      await this.show({ kind: 'receipt', receipt, cursor: 0 })
    }, 'Loading stored receipt...', brief(), (error) => {
      if (error.code === 'not_found') {
        try {
          this.journal.write()
        } catch {
          return {
            title: 'Transfer storage unavailable',
            message: 'Restore local storage to refresh the saved receipt.',
            retry: () => this.openReceipt(id), back: brief(),
          }
        }
        this.receiptId = undefined
        return {
          title: 'Receipt unavailable', message: 'The current backend has no record of this receipt.',
          retry: () => this.refresh(brief()), back: brief(),
        }
      }
    })
  }

  private async review(detail: Detail, outcome: ReviewCommand['outcome']) {
    const context = this.context
    if (!context) return
    const command: ReviewCommand = {
      operation_id: this.operationId(),
      reviewer_id: context.incomingOperatorId,
      outcome,
      reason: outcome === 'confirmed'
        ? 'Acknowledged by the incoming operator in Relay.'
        : 'Dismissed by the incoming operator in Relay.',
    }
    await this.request(async () => {
      const result = await this.api.review(detail.finding.id, command)
      if (result.finding_id !== detail.finding.id || result.reviewer_id !== command.reviewer_id
        || result.outcome !== command.outcome) {
        throw new ApiError('invalid_response', 'Review response does not match the request.')
      }
      const finding = { ...detail.finding, review_status: result.outcome }
      this.findings = orderFindings(this.findings.map(item => item.id === finding.id ? finding : item))
      await this.show({
        ...detail, finding, cursor: 0, queueIndex: this.findings.findIndex(item => item.id === finding.id),
      })
    }, 'Saving review...', detail, (error) => {
      if (error.code === 'finding_already_reviewed') {
        return {
          title: 'Finding already reviewed',
          message: 'Refresh to see the recorded review.',
          retry: () => this.refresh(brief()),
          back: brief(),
        }
      }
    })
  }

  private async request(
    load: () => Promise<void>, message: string, back?: Screen,
    recovery?: (error: ApiError) => Omit<Failure, 'kind'> | undefined,
  ) {
    await this.show({ kind: 'loading', message })
    try {
      await load()
    } catch (error) {
      const failure = error instanceof ApiError ? error : new ApiError('display', 'Could not update Relay.')
      const recovered = recovery?.(failure)
      const offline = ['network', 'timeout', 'unavailable', 'database_busy'].includes(failure.code)
      await this.show({
        kind: 'error',
        ...(recovered ?? {
          title: offline ? 'Backend unavailable' : 'Unable to continue',
          message: failure.code === 'unavailable' ? 'Check the Relay server, then retry.' : failure.message,
          retry: () => this.request(load, message, back, recovery),
          back,
        }),
      })
    }
  }

  private async show(screen: Screen) {
    await this.draw(this.render(screen))
    this.screen = screen
  }

  private render(screen: Screen): string {
    switch (screen.kind) {
      case 'configuration':
        return display('Relay | Setup needed', ['Configure a Relay backend and shift.'], 'Double tap: Exit')
      case 'loading':
        return display('Relay', [screen.message], '')
      case 'error':
        return display(`Relay | ${screen.title}`, wrapText(screen.message).slice(0, 5),
          screen.back ? 'Tap: Retry | Double tap: Back' : 'Tap: Retry | Double tap: Exit')
      case 'brief': {
        const pending = this.findings.filter(finding => finding.review_status === 'pending')
        const high = pending.filter(finding => finding.severity === 'high').length
        const warning = pending.filter(finding => finding.severity === 'warning').length
        const ai = pending.filter(finding => finding.origin === 'ai').length
        return display('Relay | Shift brief', [
          tagline,
          clip(this.context?.shiftLabel ?? 'Incoming shift'),
          clip(this.context?.incomingName ?? ''),
          `${pending.length} awaiting review: ${high} high, ${warning} warning`,
          ...menu([ai ? `Finding queue | ${ai} AI` : 'Finding queue', this.receiptId ? 'Handover receipt' : 'Handover', 'Refresh'], screen.cursor),
        ], 'Scroll: Move | Tap: Open | Double tap: Exit')
      }
      case 'queue': {
        const start = Math.floor(screen.cursor / queueSize) * queueSize
        const rows = this.findings.slice(start, start + queueSize)
          .map(finding => `${finding.origin === 'ai' ? 'AI ' : ''}${finding.severity.toUpperCase()} ${findingTitles[finding.type]}${finding.review_status === 'pending' ? '' : ' [reviewed]'}`)
        return display(`Finding queue${rows.length ? ` | ${screen.cursor + 1}/${this.findings.length}` : ''}`,
          rows.length ? menu(rows, screen.cursor - start) : ['No findings for review.'],
          rows.length ? 'Scroll: Move | Tap: Open | Double tap: Back' : 'Double tap: Back')
      }
      case 'detail':
        return display(findingTitles[screen.finding.type], [
          `${screen.finding.severity.toUpperCase()} | Review: ${screen.finding.review_status}`,
          `${screen.finding.origin === 'ai' ? 'AI proposal' : 'Deterministic finding'}${screen.finding.review_status === 'confirmed' ? ' | Human confirmed' : ''}`,
          ...(screen.finding.uncertainty ? ['Uncertainty: ' + clip(screen.finding.uncertainty, 32)] : []),
          ...excerpt(screen.finding.explanation, screen.finding.uncertainty ? 1 : 2),
          ...menu(screen.finding.review_status === 'pending' ? ['Source evidence', 'Review finding', 'Finding notes'] : ['Source evidence', 'Finding notes'], screen.cursor),
        ], 'Scroll: Move | Tap: Open | Double tap: Back')
      case 'evidence': {
        const page = screen.pages[screen.cursor]
        return display(page.heading, [page.source, page.status, ...page.lines],
          screen.back.finding.review_status === 'pending'
            ? 'Scroll: Compare | Tap: Review | 2x: Back'
            : 'Scroll: Compare | Double tap: Back')
      }
      case 'notes':
        return display(`Finding notes | ${screen.cursor + 1}/${Math.ceil(screen.lines.length / 6)}`,
          screen.lines.slice(screen.cursor * 6, screen.cursor * 6 + 6),
          'Scroll: Notes | Double tap: Back')
      case 'review':
        return display('Review finding', [
          findingTitles[screen.detail.finding.type],
          ...menu(['Cancel', 'Acknowledge finding', screen.detail.finding.origin === 'ai' ? 'Reject AI proposal' : 'Dismiss finding'], screen.cursor),
        ], 'Scroll: Choose | Tap: Select | Double tap: Back')
      case 'preview': {
        const { actions } = screen.handover
        const eligible = actions.filter(item => item.transferable).length
        const selected = itemPages(actions)[screen.cursor]
        return display('Handover preview', [
          clip(this.context?.incomingName ?? 'Incoming operator'),
          `${eligible} eligible | ${actions.length - eligible} stay outgoing`,
          `${selected.index + 1}/${actions.length} | ${selected.item.transferable ? 'Will transfer' : 'Stays outgoing'}${selected.suffix}`,
          ...selected.lines,
        ], eligible ? 'Scroll: Items | Tap: Review | Double tap: Back' : 'Scroll: Items | Double tap: Back')
      }
      case 'confirm': {
        const items = screen.preview.handover.actions
        const eligible = items.filter(item => item.transferable).length
        return display('Confirm transfer', [
          clip(`Accept as ${this.context?.incomingName ?? 'incoming operator'}`),
          `${eligible} transfer | ${items.length - eligible} stay outgoing`,
          'Accepting changes the owner in Relay.',
          ...menu(['Cancel', 'Accept responsibility'], screen.cursor),
        ], 'Scroll: Choose | Tap: Select | Double tap: Back')
      }
      case 'receipt': {
        const { transferred, outstanding, id, notion_sync } = screen.receipt
        const actions = [...transferred, ...outstanding]
        const selected = itemPages(actions)[screen.cursor]
        return display('Handover receipt | Accepted', [
          `${transferred.length} transferred | ${outstanding.length} outstanding`,
          id,
          ...(notion_sync ? [notion_sync === "synced" ? "Notion: Synced" : notion_sync === "uncertain" ? "Notion: Check pending write" : "Notion: Sync pending"] : []),
          `${selected.index + 1}/${actions.length} | ${selected.index < transferred.length ? 'Transferred' : 'Outstanding'}${selected.suffix}`,
          ...selected.lines,
        ], 'Scroll: Items | Double tap: Back')
      }
    }
  }
}
