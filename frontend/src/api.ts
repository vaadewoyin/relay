type Check<T> = (value: unknown) => value is T
type Accepted<T> = T extends Check<infer Result> ? Result : never

function record<S extends Record<string, Check<unknown>>>(shape: S) {
  return (value: unknown): value is { [Key in keyof S]: Accepted<S[Key]> } =>
    typeof value === 'object' && value !== null && !Array.isArray(value)
    && Object.entries(shape).every(([key, check]) => check((value as Record<string, unknown>)[key]))
}

const text: Check<string> = (value): value is string => typeof value === 'string' && value.trim().length > 0
const id: Check<string> = (value): value is string => typeof value === 'string'
  && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
const timestamp: Check<string> = (value): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value))
const version: Check<number> = (value): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value > 0
const flag: Check<boolean> = (value): value is boolean => typeof value === 'boolean'

function oneOf<const T extends readonly string[]>(...options: T): Check<T[number]> {
  return (value): value is T[number] => typeof value === 'string' && options.includes(value)
}

function list<T>(check: Check<T>, minimum = 0): Check<T[]> {
  return (value): value is T[] => Array.isArray(value) && value.length >= minimum && value.every(check)
}

function nullable<T>(check: Check<T>): Check<T | null> {
  return (value): value is T | null => value === null || check(value)
}

const evidence = record({ report_id: id, source_ref: text, quote: text })
const finding = record({
  id,
  type: oneOf('missing_owner', 'overdue_action', 'duplicate_report', 'stale_version',
    'unresolved_responsibility', 'contradictory_asset_status', 'semantic_contradiction',
    'unsupported_completion', 'ambiguous_ownership', 'missing_operational_context',
    'unresolved_safety_concern', 'inconsistent_completion', 'potential_duplicate_incident'),
  severity: oneOf('info', 'warning', 'high'),
  explanation: text,
  evidence: list(evidence, 1),
  recommended_action: text,
  review_status: oneOf('pending', 'confirmed', 'dismissed'),
  created_at: timestamp,
  origin: oneOf('deterministic', 'ai'),
  execution_id: nullable(id),
  uncertainty: nullable(text),
})
const actionFields = {
  report_id: id,
  description: text,
  owner_id: nullable(id),
  status: oneOf('open', 'in_progress', 'resolved'),
  due_at: nullable(timestamp),
  version,
}
const action = record({ ...actionFields, id, shift_id: id, updated_at: timestamp })
const reportDetails = record({
  report: record({
    id,
    source_ref: text,
    shift_id: id,
    author_id: id,
    asset_id: id,
    observed_at: timestamp,
    text,
    asset_status: nullable(oneOf('operational', 'faulted', 'out_of_service')),
    synthetic: flag,
    received_at: timestamp,
  }),
  actions: list(action),
})
const review = record({
  id, finding_id: id, reviewer_id: id, outcome: oneOf('confirmed', 'dismissed'), reason: text, decided_at: timestamp,
})
const handover = record({
  id,
  outgoing_shift_id: id,
  incoming_shift_id: id,
  outgoing_operator_id: id,
  incoming_operator_id: id,
  actions: list(record({ ...actionFields, action_id: id, transferable: flag }), 1),
  status: oneOf('previewed', 'accepted'),
  version,
  created_at: timestamp,
})
const receipt = record({
  id,
  handover_id: id,
  outgoing_shift_id: id,
  incoming_shift_id: id,
  accepted_by: id,
  accepted_at: timestamp,
  transferred: list(action, 1),
  outstanding: list(action),
})
const health = record({ status: oneOf('ok') })
const errorBody = record({ code: text, message: text, request_id: text })

export type Finding = Accepted<typeof finding>
export type EvidenceReference = Accepted<typeof evidence>
export type SourceReport = Accepted<typeof reportDetails>['report']
export type ReviewDecision = Accepted<typeof review>
export type Handover = Accepted<typeof handover>
export type Receipt = Accepted<typeof receipt>

export type ReviewCommand = {
  operation_id: string
  reviewer_id: string
  outcome: ReviewDecision['outcome']
  reason: string
}
export type PreviewCommand = {
  operation_id: string
  outgoing_shift_id: string
  incoming_shift_id: string
  actor_id: string
}
export type AcceptCommand = {
  operation_id: string
  actor_id: string
  expected_version: number
  confirmed: true
}

export class ApiError extends Error {
  readonly code: string
  readonly status?: number

  constructor(code: string, message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

export class RelayApi {
  private readonly base: string
  private readonly fetcher: typeof fetch
  private readonly timeoutMs: number

  constructor(base: string, fetcher: typeof fetch = fetch, timeoutMs = 6000) {
    this.base = base.replace(/\/$/, '')
    this.fetcher = fetcher
    this.timeoutMs = timeoutMs
  }

  health() { return this.request('/health', health) }
  findings() { return this.request('/findings', list(finding)) }
  finding(id: string) { return this.request(`/findings/${encodeURIComponent(id)}`, finding) }
  report(id: string) { return this.request(`/reports/${encodeURIComponent(id)}`, reportDetails) }
  review(id: string, command: ReviewCommand) {
    return this.request(`/findings/${encodeURIComponent(id)}/reviews`, review, command)
  }
  preview(command: PreviewCommand) { return this.request('/handovers', handover, command) }
  accept(id: string, command: AcceptCommand) {
    return this.request(`/handovers/${encodeURIComponent(id)}/acceptance`, receipt, command)
  }
  receipt(id: string) {
    return this.request(`/handover-receipts/${encodeURIComponent(id)}`, receipt)
  }

  private async request<T>(
    path: string,
    check: Check<T>,
    command?: ReviewCommand | PreviewCommand | AcceptCommand,
  ): Promise<T> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)
    try {
      const response = await this.fetcher(`${this.base}${path}`, {
        signal: controller.signal,
        cache: 'no-store',
        headers: command ? { 'Content-Type': 'application/json' } : undefined,
        method: command ? 'POST' : 'GET',
        body: command ? JSON.stringify(command) : undefined,
      })
      const data: unknown = await response.json().catch((error: unknown) => {
        if (controller.signal.aborted) throw error
        return undefined
      })
      if (!response.ok) {
        if (errorBody(data)) throw new ApiError(data.code, data.message, response.status)
        throw new ApiError(
          response.status >= 500 ? 'unavailable' : 'http_error',
          response.status >= 500 ? 'Backend unavailable.' : 'Backend rejected the request.',
          response.status,
        )
      }
      if (!check(data)) throw new ApiError('invalid_response', 'Backend returned an invalid response.')
      return data
    } catch (error) {
      if (error instanceof ApiError) throw error
      if (controller.signal.aborted) throw new ApiError('timeout', 'Backend request timed out.')
      throw new ApiError('network', 'Could not reach the backend.')
    } finally {
      clearTimeout(timer)
    }
  }
}
