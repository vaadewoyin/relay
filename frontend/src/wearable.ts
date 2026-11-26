import { ApiError } from './api.ts'
import type { Finding, Handover, PreviewCommand, RelayApi, ReviewCommand } from './api.ts'
import type { ShiftContext } from './shift-context.ts'
import { clip, display, evidencePages, findingTitles, menu, orderFindings, wrapText } from './view.ts'
import type { EvidencePage } from './view.ts'

export type Gesture = 'up' | 'down' | 'tap' | 'back'

type Brief = { kind: 'brief'; cursor: number }
type Queue = { kind: 'queue'; cursor: number }
type Detail = { kind: 'detail'; finding: Finding; cursor: number; queueIndex: number }
type Preview = { kind: 'preview'; handover: Handover; cursor: number }
type Screen =
  | Brief | Queue | Detail | Preview
  | { kind: 'evidence'; pages: EvidencePage[]; cursor: number; back: Detail }
  | { kind: 'review'; detail: Detail; cursor: number }
  | { kind: 'loading'; message: string }
  | { kind: 'error'; title: string; message: string; retry: () => Promise<void>; back?: Screen }
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
  private screen: Screen = { kind: 'loading', message: 'Connecting to Relay...' }
  private findings: Finding[] = []
  private busy = false
  private lastTap = -Infinity

  constructor(options: {
    api: RelayApi
    context?: ShiftContext
    draw: (content: string) => Promise<void>
    exit: () => Promise<void>
    clock?: () => number
    operationId?: () => string
  }) {
    this.api = options.api
    this.context = options.context
    this.draw = options.draw
    this.exit = options.exit
    this.clock = options.clock ?? (() => performance.now())
    this.operationId = options.operationId ?? (() => crypto.randomUUID())
  }

  async start() {
    this.busy = true
    try {
      await (this.context ? this.refresh() : this.show({ kind: 'configuration' }))
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
      detail: current.kind === 'detail' && current.finding.review_status === 'pending' ? 2 : 1,
      evidence: current.kind === 'evidence' ? current.pages.length : 0,
      review: 3,
      preview: current.kind === 'preview' ? current.handover.actions.length : 0,
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
      case 'detail':
        await this.show({ kind: 'queue', cursor: current.queueIndex })
        break
      case 'evidence':
        await this.show(current.back)
        break
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
        else if (current.cursor === 1) await this.openPreview()
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
        else await this.show({ kind: 'review', detail: current, cursor: 0 })
        break
      case 'review':
        if (current.cursor === 0) await this.show(current.detail)
        else await this.review(current.detail, current.cursor === 1 ? 'confirmed' : 'dismissed')
        break
      case 'error':
        await current.retry()
        break
    }
  }

  private async refresh(back?: Screen) {
    await this.request(async () => {
      await this.api.health()
      this.findings = orderFindings(await this.api.findings())
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
          || report.text !== reference.quote) {
          throw new ApiError('invalid_response', 'Evidence does not match the source report.')
        }
        pages.push(...evidencePages(report, index, references.length))
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
    recovery?: (error: ApiError) => Omit<Extract<Screen, { kind: 'error' }>, 'kind'> | undefined,
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
          message: failure.message,
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
        return display('Relay', [screen.message], 'Please wait')
      case 'error':
        return display(`Relay | ${screen.title}`, wrapText(screen.message).slice(0, 5),
          screen.back ? 'Tap: Retry | Double tap: Back' : 'Tap: Retry | Double tap: Exit')
      case 'brief': {
        const pending = this.findings.filter(finding => finding.review_status === 'pending')
        const high = pending.filter(finding => finding.severity === 'high').length
        const warning = pending.filter(finding => finding.severity === 'warning').length
        return display('Relay | Shift brief', [
          clip(this.context?.shiftLabel ?? 'Incoming shift'),
          clip(this.context?.incomingName ?? ''),
          `${pending.length} awaiting review: ${high} high, ${warning} warning`,
          ...menu(['Finding queue', 'Handover', 'Refresh'], screen.cursor),
        ], 'Scroll: Move | Tap: Open | Double tap: Exit')
      }
      case 'queue': {
        const start = Math.floor(screen.cursor / queueSize) * queueSize
        const rows = this.findings.slice(start, start + queueSize)
          .map(finding => `${finding.severity.toUpperCase()} ${findingTitles[finding.type]}${finding.review_status === 'pending' ? '' : ' [reviewed]'}`)
        return display(`Finding queue${rows.length ? ` | ${screen.cursor + 1}/${this.findings.length}` : ''}`,
          rows.length ? menu(rows, screen.cursor - start) : ['No findings for review.'],
          rows.length ? 'Scroll: Move | Tap: Open | Double tap: Back' : 'Double tap: Back')
      }
      case 'detail':
        return display(findingTitles[screen.finding.type], [
          `${screen.finding.severity.toUpperCase()} | Review: ${screen.finding.review_status}`,
          ...wrapText(screen.finding.explanation).slice(0, 3),
          ...menu(screen.finding.review_status === 'pending' ? ['Source evidence', 'Review finding'] : ['Source evidence'], screen.cursor),
        ], 'Scroll: Move | Tap: Open | Double tap: Back')
      case 'evidence': {
        const page = screen.pages[screen.cursor]
        return display(page.heading, [page.source, page.status, ...page.lines],
          'Scroll: Sources/pages | Double tap: Back')
      }
      case 'review':
        return display('Review finding', [
          findingTitles[screen.detail.finding.type],
          'Choose the review to record.',
          ...menu(['Cancel', 'Acknowledge finding', 'Dismiss finding'], screen.cursor),
        ], 'Scroll: Choose | Tap: Select | Double tap: Back')
      case 'preview': {
        const { actions } = screen.handover
        const eligible = actions.filter(item => item.transferable).length
        const selected = actions[screen.cursor]
        return display('Handover preview', [
          clip(this.context?.incomingName ?? 'Incoming operator'),
          `${eligible} eligible | ${actions.length - eligible} stay outgoing`,
          `${screen.cursor + 1}/${actions.length} | ${selected.transferable ? 'Will transfer' : 'Stays outgoing'}`,
          ...wrapText(selected.description).slice(0, 3),
        ], 'Scroll: Work items | Double tap: Back')
      }
    }
  }
}
