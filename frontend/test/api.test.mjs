import assert from 'node:assert/strict'
import test from 'node:test'
import { RelayApi } from '../src/api.ts'

const json = (value, status = 200) => new Response(JSON.stringify(value), { status })

test('API client handles health, queue and source routes', async () => {
  const calls = []
  const api = new RelayApi('/relay-api/', async (url, options) => {
    calls.push([url, options.method])
    return url.endsWith('/health') ? json({ status: 'ok' }) : json([])
  })
  assert.deepEqual(await api.health(), { status: 'ok' })
  assert.deepEqual(await api.findings(), [])
  await assert.rejects(api.report('a/b'), { code: 'invalid_response' })
  assert.deepEqual(calls, [
    ['/relay-api/health', 'GET'],
    ['/relay-api/findings', 'GET'],
    ['/relay-api/reports/a%2Fb', 'GET'],
  ])
})

test('API client preserves operation IDs and structured conflicts', async () => {
  const requests = []
  const error = { code: 'stale_version', message: 'Create a fresh preview.', request_id: 'server-id' }
  const api = new RelayApi('/relay-api', async (url, options) => {
    requests.push([url, options.method, JSON.parse(options.body)])
    return json(error, 409)
  })
  const command = { operation_id: 'attempt', actor_id: 'recipient', expected_version: 1, confirmed: true }
  await assert.rejects(api.accept('preview', command), { code: 'stale_version', status: 409 })
  await assert.rejects(api.accept('preview', command), { code: 'stale_version', status: 409 })
  assert.deepEqual(requests, [
    ['/relay-api/handovers/preview/acceptance', 'POST', command],
    ['/relay-api/handovers/preview/acceptance', 'POST', command],
  ])
})

test('API client distinguishes timeout, disconnect, server failure and malformed receipt', async () => {
  const timeout = new RelayApi('', (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true })
  }), 10)
  await assert.rejects(timeout.health(), { code: 'timeout' })
  const offline = new RelayApi('', async () => { throw new TypeError('connection reset') })
  await assert.rejects(offline.health(), { code: 'network' })
  const unavailable = new RelayApi('', async () => new Response('proxy unavailable', { status: 503 }))
  await assert.rejects(unavailable.health(), { code: 'unavailable', status: 503 })
  const invalid = new RelayApi('', async () => json({ id: 'something', transferred: [] }))
  await assert.rejects(invalid.receipt('x'), { code: 'invalid_response' })
})
