import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError } from '../src/api.ts'
import { localJournal, memoryJournal } from '../src/transfer-journal.ts'
import { orderFindings, wrapText } from '../src/view.ts'
import { Wearable } from '../src/wearable.ts'

const context = {
  outgoingShiftId: 'day', incomingShiftId: 'evening', outgoingOperatorId: 'ada',
  incomingOperatorId: 'tunde', incomingName: 'Synthetic maintainer Tunde',
  shiftLabel: 'Evening shift | Synthetic',
}
const source = {
  id: 'report-1', source_ref: 'synthetic:report',
  text: 'Synthetic report: Pump P-17 tripped twice under load. The dock bypass is active.',
  asset_status: 'faulted',
}
const high = {
  id: 'high', type: 'overdue_action', severity: 'high', review_status: 'pending',
  created_at: '2025-11-26T13:50:00Z',
  explanation: 'An unresolved action is past its due time.',
  evidence: [{ report_id: source.id, source_ref: source.source_ref, quote: source.text }],
  recommended_action: 'Review and prioritize the action.',
}
const warning = {
  ...high, id: 'warn', type: 'missing_owner', severity: 'warning',
  explanation: 'An unresolved action has no owner.',
}

function harness(overrides = {}, journal) {
  const records = [warning, high]
  let frame = ''
  let now = 0
  let operation = 0
  const api = {
    health: async () => ({ status: 'ok' }),
    findings: async () => records,
    finding: async id => records.find(record => record.id === id),
    report: async () => ({ report: source }),
    review: async (id, command) => ({
      finding_id: id, reviewer_id: command.reviewer_id, outcome: command.outcome,
    }),
    ...overrides,
  }
  const app = new Wearable({
    api, context, draw: async content => { frame = content }, exit: async () => {},
    clock: () => now, operationId: () => `operation-${++operation}`, journal,
  })
  return {
    app, frame: () => frame,
    async go(...gestures) {
      for (const gesture of gestures) {
        now += 500
        await app.input(gesture)
      }
    },
  }
}

test('orders pending findings before reviewed and high severity before warning', () => {
  const reviewed = { ...high, id: 'reviewed', review_status: 'confirmed' }
  assert.deepEqual(orderFindings([warning, reviewed, high]).map(item => item.id), [
    'high', 'warn', 'reviewed',
  ])
})

test('navigates from shift brief to prioritized queue, finding and traceable evidence', async () => {
  const { app, frame, go } = harness()
  await app.start()
  assert.match(frame(), /2 awaiting review: 1 high, 1 warning/)
  await go('tap')
  assert.match(frame(), /> HIGH Overdue action/)
  await go('tap')
  assert.match(frame(), /Review: pending/)
  await go('tap')
  assert.match(frame(), /Source 1\/1/)
  assert.match(frame(), /synthetic:report\nfaulted/)
  assert.match(frame(), /Pump P-17 tripped twice/)
  await go('back', 'back')
  assert.match(frame(), /Finding queue/)
  await go('down', 'tap')
  assert.match(frame(), /Missing action owner/)
  assert.equal(wrapText('x'.repeat(100)).join(''), 'x'.repeat(100))
})

test('invalid provenance is recoverable and never displayed as source evidence', async () => {
  const { app, frame, go } = harness({
    report: async () => ({ report: { ...source, text: 'changed content' } }),
  })
  await app.start()
  await go('tap', 'tap', 'tap')
  assert.match(frame(), /Evidence does not match/)
  assert.doesNotMatch(frame(), /changed content/)
  await go('back')
  assert.match(frame(), /Overdue action/)
})

test('review defaults to cancel and a retry reuses the original operation ID', async () => {
  const calls = []
  const { app, frame, go } = harness({
    async review(id, command) {
      calls.push(command.operation_id)
      if (calls.length === 1) throw new ApiError('network', 'Disconnected.')
      return { finding_id: id, reviewer_id: command.reviewer_id, outcome: command.outcome }
    },
  })
  await app.start()
  await go('tap', 'tap', 'down', 'tap')
  assert.match(frame(), /> Cancel/)
  await app.input('tap')
  assert.equal(calls.length, 0)
  await go('tap')
  assert.equal(calls.length, 0)
  await go('tap', 'down', 'tap')
  assert.match(frame(), /Backend unavailable/)
  await go('tap')
  assert.deepEqual(calls, ['operation-1', 'operation-1'])
  assert.match(frame(), /Review: confirmed/)
})

test('connection recovery reaches the brief and an empty queue has a clear state', async () => {
  let available = false
  const { app, frame, go } = harness({
    health: async () => {
      if (!available) throw new ApiError('unavailable', 'Backend unavailable.')
      return { status: 'ok' }
    },
    findings: async () => [],
  })
  await app.start()
  assert.match(frame(), /Backend unavailable/)
  available = true
  await go('tap')
  assert.match(frame(), /Shift brief/)
  await go('tap', 'tap')
  assert.match(frame(), /No findings for review/)
  await go('back')
  assert.match(frame(), /Shift brief/)
})

const handover = {
  id: 'preview', status: 'previewed', version: 1,
  outgoing_shift_id: 'day', incoming_shift_id: 'evening',
  outgoing_operator_id: 'ada', incoming_operator_id: 'tunde',
  actions: [
    { action_id: 'pump', transferable: true, description: 'Test pump P-17.' },
    { action_id: 'bypass', transferable: false, description: 'Assign bypass inspection.' },
  ],
}

test('handover preview shows eligible and outstanding work without accepting it', async () => {
  const commands = []
  const { app, frame, go } = harness({
    async preview(command) { commands.push(command); return handover },
    async accept() { assert.fail('Preview is read-only for responsibility.') },
  })
  await app.start()
  await go('down', 'tap')
  assert.match(frame(), /1 eligible \| 1 stay outgoing/)
  assert.match(frame(), /Will transfer\nTest pump P-17/)
  await go('down')
  assert.match(frame(), /Stays outgoing\nAssign bypass/)
  await go('back')
  assert.match(frame(), /Shift brief/)
  assert.deepEqual(commands, [{
    operation_id: 'operation-1', actor_id: 'ada', outgoing_shift_id: 'day', incoming_shift_id: 'evening',
  }])
})

const storedReceipt = {
  id: 'receipt-id', handover_id: 'preview', outgoing_shift_id: 'day',
  incoming_shift_id: 'evening', accepted_by: 'tunde',
  transferred: [{ description: 'Test pump P-17.' }],
  outstanding: [{ description: 'Assign bypass inspection.' }],
}

test('transfer needs a separate armed choice and duplicate gestures produce one acceptance', async () => {
  const accepted = []
  let finish
  let started
  const entered = new Promise(resolve => { started = resolve })
  const { app, frame, go } = harness({
    preview: async () => handover,
    async accept(id, command) {
      accepted.push([id, command])
      started()
      return new Promise(resolve => { finish = () => resolve(storedReceipt) })
    },
    receipt: async () => storedReceipt,
  })
  await app.start()
  await go('down', 'tap', 'tap')
  assert.match(frame(), /> Cancel/)
  await go('tap')
  assert.match(frame(), /Handover preview/)
  assert.equal(accepted.length, 0)
  await go('tap', 'down')
  const acceptance = go('tap')
  await entered
  await go('tap', 'tap', 'down', 'back')
  assert.equal(accepted.length, 1)
  assert.match(frame(), /Verifying transfer receipt/)
  finish()
  await acceptance
  assert.deepEqual(accepted, [['preview', {
    operation_id: 'operation-2', actor_id: 'tunde', expected_version: 1, confirmed: true,
  }]])
  assert.match(frame(), /Handover receipt \| Accepted/)
  assert.match(frame(), /1 transferred \| 1 outstanding/)
  assert.match(frame(), /receipt-id/)
  await go('down')
  assert.match(frame(), /Outstanding\nAssign bypass inspection/)
  await go('back', 'down', 'tap')
  assert.match(frame(), /Handover receipt \| Accepted/)
  assert.equal(accepted.length, 1)
})

test('ambiguous receipt response keeps the operation for retry after a reload', async () => {
  const journal = memoryJournal()
  const attempts = []
  const accept = async (_id, command) => {
    attempts.push(command.operation_id)
    return storedReceipt
  }
  const first = harness({
    preview: async () => handover, accept,
    receipt: async () => ({ ...storedReceipt, accepted_by: 'unexpected' }),
  }, journal)
  await first.app.start()
  await first.go('down', 'tap', 'tap', 'down', 'tap')
  assert.match(first.frame(), /Transfer status unknown/)
  assert.doesNotMatch(first.frame(), /Handover receipt \| Accepted/)
  assert.equal(journal.read().kind, 'pending')
  const reopened = harness({ accept, receipt: async () => storedReceipt }, journal)
  await reopened.app.start()
  assert.match(reopened.frame(), /Retry the same\s+confirmed transfer/)
  assert.deepEqual(attempts, ['operation-2'])
  await reopened.go('tap')
  assert.deepEqual(attempts, ['operation-2', 'operation-2'])
  assert.match(reopened.frame(), /Handover receipt \| Accepted/)
  assert.deepEqual(journal.read(), { kind: 'receipt', receiptId: 'receipt-id' })
})

test('stale preview requires a fresh preview and another explicit confirmation', async () => {
  const journal = memoryJournal()
  let previews = 0
  const calls = []
  const { app, frame, go } = harness({
    preview: async () => ({ ...handover, id: `preview-${++previews}` }),
    async accept(id, command) {
      calls.push([id, command.operation_id])
      if (id === 'preview-1') throw new ApiError('stale_version', 'Stale.', 409)
      return { ...storedReceipt, handover_id: id }
    },
    receipt: async () => ({ ...storedReceipt, handover_id: 'preview-2' }),
  }, journal)
  await app.start()
  await go('down', 'tap', 'tap', 'down', 'tap')
  assert.match(frame(), /Preview changed/)
  assert.equal(journal.read(), undefined)
  await go('tap')
  assert.match(frame(), /Handover preview/)
  assert.equal(calls.length, 1)
  await go('tap')
  assert.match(frame(), /> Cancel/)
  await go('down', 'tap')
  assert.match(frame(), /Handover receipt \| Accepted/)
  assert.deepEqual(calls, [['preview-1', 'operation-2'], ['preview-2', 'operation-4']])
})

test('acceptance fails closed if the operation cannot be written to local storage', async () => {
  const { app, frame, go } = harness({
    preview: async () => handover,
    accept: async () => { assert.fail('Must record an operation before a transfer.') },
  }, { read: () => undefined, write: () => { throw new Error('storage unavailable') } })
  await app.start()
  await go('down', 'tap', 'tap', 'down', 'tap')
  assert.match(frame(), /Transfer storage unavailable/)
})

test('local transfer journal is scoped and recovers exactly the original command', () => {
  const values = new Map()
  const storage = () => ({
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  })
  const incomingOperatorId = crypto.randomUUID()
  const setup = { ...context, incomingOperatorId }
  const pending = {
    kind: 'pending', handoverId: crypto.randomUUID(),
    command: {
      operation_id: crypto.randomUUID(), actor_id: incomingOperatorId,
      expected_version: 2, confirmed: true,
    },
  }
  localJournal(storage, '/relay-api', setup).write(pending)
  const reopened = localJournal(storage, '/relay-api', setup)
  assert.deepEqual(reopened.read(), pending)
  assert.equal(localJournal(storage, 'https://demo.invalid', setup).read(), undefined)
  reopened.write()
  assert.equal(reopened.read(), undefined)
})

test('an AI proposal shows exact report excerpts and retains its origin after human review', async () => {
  const ai = {
    ...high, id: 'ai', origin: 'ai', type: 'semantic_contradiction',
    uncertainty: 'Timing should be confirmed.',
    evidence: [{ ...high.evidence[0], quote: 'Pump P-17 tripped twice under load.' }],
  }
  const { app, frame, go } = harness({
    findings: async () => [ai, warning], finding: async () => ai,
  })
  await app.start()
  assert.match(frame(), /1 AI proposal awaiting review/)
  await go('tap')
  assert.match(frame(), /AI HIGH Conflicting reports/)
  await go('tap')
  assert.match(frame(), /AI proposal/)
  assert.match(frame(), /Uncertainty: Timing/)
  assert.ok(frame().split('\n').length <= 9)
  await go('tap')
  assert.match(frame(), /Pump P-17 tripped twice under load/)
  assert.doesNotMatch(frame(), /bypass is active/)
  await go('back', 'down', 'tap')
  assert.match(frame(), /Reject AI proposal/)
  await go('down', 'tap')
  assert.match(frame(), /AI proposal \| Human confirmed/)
})

test('the local accepted receipt remains visible while external Notion sync is pending', async () => {
  let state = 'pending'
  const { app, frame, go } = harness({
    preview: async () => handover,
    accept: async () => storedReceipt,
    receipt: async () => ({ ...storedReceipt, notion_sync: state }),
  })
  await app.start()
  await go('down', 'tap', 'tap', 'down', 'tap')
  assert.match(frame(), /Handover receipt \| Accepted/)
  assert.match(frame(), /Notion: Sync pending/)
  state = 'synced'
  await go('back', 'down', 'tap')
  assert.match(frame(), /Notion: Synced/)
})
