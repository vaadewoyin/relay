import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import * as sdk from '@evenrealities/even_hub_sdk'

test('Relay starts a captured text page, counts taps and exits on double tap', async () => {
  let emit
  const create = mock.fn(async () => 0)
  const upgrade = mock.fn(async () => true)
  const exit = mock.fn(async () => true)
  const unsubscribe = mock.fn()
  const bridge = {
    createStartUpPageContainer: create,
    textContainerUpgrade: upgrade,
    shutDownPageContainer: exit,
    onEvenHubEvent(listener) {
      emit = listener
      return unsubscribe
    },
  }
  const sdkMock = mock.module('@evenrealities/even_hub_sdk', {
    namedExports: { ...sdk, waitForEvenAppBridge: async () => bridge },
  })

  try {
    await import('../src/main.ts')
    const [page] = create.mock.calls[0].arguments
    assert.match(page.textObject[0].content, /^Hello, Relay\n/)
    assert.equal(page.textObject[0].isEventCapture, 1)

    emit({ textEvent: { eventType: sdk.OsEventTypeList.SCROLL_TOP_EVENT } })
    emit({ textEvent: { eventType: sdk.OsEventTypeList.SCROLL_BOTTOM_EVENT } })
    emit({})
    assert.equal(upgrade.mock.callCount(), 0)

    emit({ sysEvent: { eventSource: 1 } })
    emit({ sysEvent: { eventType: sdk.OsEventTypeList.CLICK_EVENT } })
    assert.match(upgrade.mock.calls[0].arguments[0].content, /^Hello, Relay\nTaps: 1\n/)
    assert.match(upgrade.mock.calls[1].arguments[0].content, /^Hello, Relay\nTaps: 2\n/)

    emit({ sysEvent: { eventType: sdk.OsEventTypeList.DOUBLE_CLICK_EVENT } })
    assert.deepEqual(exit.mock.calls[0].arguments, [1])
    assert.equal(upgrade.mock.callCount(), 2)

    emit({ sysEvent: { eventType: sdk.OsEventTypeList.SYSTEM_EXIT_EVENT } })
    assert.equal(unsubscribe.mock.callCount(), 1)
  } finally {
    sdkMock.restore()
  }
})
