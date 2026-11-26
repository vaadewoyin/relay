import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError } from '../src/api.ts'
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

function harness(overrides = {}) {
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
    clock: () => now, operationId: () => `operation-${++operation}`,
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
