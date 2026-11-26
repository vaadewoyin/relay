/// <reference types="vite/client" />

import {
  waitForEvenAppBridge, TextContainerProperty, CreateStartUpPageContainer,
  TextContainerUpgrade, OsEventTypeList,
} from '@evenrealities/even_hub_sdk'
import { RelayApi } from './api.ts'
import { parseShiftContext } from './shift-context.ts'
import { localJournal } from './transfer-journal.ts'
import { Wearable } from './wearable.ts'

const bridge = await waitForEvenAppBridge()
const containerID = 1
const containerName = 'relay'
const result = await bridge.createStartUpPageContainer(
  new CreateStartUpPageContainer({
    containerTotalNum: 1,
    textObject: [new TextContainerProperty({
      xPosition: 0, yPosition: 0, width: 576, height: 288,
      borderWidth: 0, paddingLength: 10, containerID, containerName,
      content: 'Relay\nConnecting...', isEventCapture: 1,
    })],
  }),
)
if (result !== 0) throw new Error(`Could not create glasses page (${result}).`)

const env = import.meta.env
const base = env?.VITE_RELAY_API_BASE || (env?.DEV ? '/relay-api' : undefined)
const context = base ? parseShiftContext(env?.VITE_RELAY_CONTEXT) : undefined
const wearable = new Wearable({
  api: new RelayApi(base ?? '/relay-api'),
  context,
  journal: base && context ? localJournal(() => localStorage, base, context) : undefined,
  async draw(content) {
    const updated = await bridge.textContainerUpgrade(new TextContainerUpgrade({
      containerID, containerName, content, contentOffset: 0, contentLength: 0,
    }))
    if (!updated) throw new Error('Could not update glasses page.')
    console.debug('Relay screen:', content.split('\n', 1)[0])
  },
  async exit() { await bridge.shutDownPageContainer(1) },
})

const unsubscribe = bridge.onEvenHubEvent(event => {
  const sys = event.sysEvent ? event.sysEvent.eventType ?? OsEventTypeList.CLICK_EVENT : undefined
  const text = event.textEvent?.eventType
  if (sys === OsEventTypeList.SYSTEM_EXIT_EVENT || sys === OsEventTypeList.ABNORMAL_EXIT_EVENT) {
    unsubscribe()
    return
  }
  const run = (gesture: Parameters<typeof wearable.input>[0]) => {
    void wearable.input(gesture).catch(error => console.error('Relay display error', error))
  }
  if (sys === OsEventTypeList.DOUBLE_CLICK_EVENT || text === OsEventTypeList.DOUBLE_CLICK_EVENT) run('back')
  else if (sys === OsEventTypeList.CLICK_EVENT) run('tap')
  else if (text === OsEventTypeList.SCROLL_TOP_EVENT) run('up')
  else if (text === OsEventTypeList.SCROLL_BOTTOM_EVENT) run('down')
})

await wearable.start()
