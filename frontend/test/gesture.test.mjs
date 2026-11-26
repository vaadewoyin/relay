import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import * as sdk from '@evenrealities/even_hub_sdk'

test('SDK entry creates one capturing glasses page and retains the root exit gesture', async () => {
  let emit
  const create = mock.fn(async () => 0)
  const upgrade = mock.fn(async () => true)
  const exit = mock.fn(async () => true)
  const unsubscribe = mock.fn()
  const sdkMock = mock.module('@evenrealities/even_hub_sdk', {
    namedExports: {
      ...sdk,
      waitForEvenAppBridge: async () => ({
        createStartUpPageContainer: create,
        textContainerUpgrade: upgrade,
        shutDownPageContainer: exit,
        onEvenHubEvent(listener) { emit = listener; return unsubscribe },
      }),
    },
  })

  try {
    await import('../src/main.ts')
    const [page] = create.mock.calls[0].arguments
    assert.equal(page.containerTotalNum, 1)
    assert.equal(page.textObject[0].isEventCapture, 1)
    assert.equal(page.textObject[0].width, 576)
    assert.equal(page.textObject[0].height, 288)
    assert.match(upgrade.mock.calls[0].arguments[0].content, /Setup needed/)
    emit({})
    emit({ textEvent: { eventType: sdk.OsEventTypeList.SCROLL_TOP_EVENT } })
    assert.equal(exit.mock.callCount(), 0)
    emit({ sysEvent: { eventType: sdk.OsEventTypeList.DOUBLE_CLICK_EVENT } })
    assert.deepEqual(exit.mock.calls[0].arguments, [1])
    emit({ sysEvent: { eventType: sdk.OsEventTypeList.SYSTEM_EXIT_EVENT } })
    assert.equal(unsubscribe.mock.callCount(), 1)
  } finally {
    sdkMock.restore()
  }
})
