import type { AcceptCommand } from './api.ts'
import type { ShiftContext } from './shift-context.ts'

export type PendingTransfer = { kind: 'pending'; handoverId: string; command: AcceptCommand }
type ReceiptPointer = { kind: 'receipt'; receiptId: string }
export type TransferEntry = PendingTransfer | ReceiptPointer

export type TransferJournal = {
  read(): TransferEntry | undefined
  write(entry?: TransferEntry): void
}

export function memoryJournal(): TransferJournal {
  let entry: TransferEntry | undefined
  return {
    read: () => entry,
    write: (next) => { entry = next },
  }
}

const uuid = (value: unknown): value is string => typeof value === 'string'
  && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)

export function localJournal(
  storage: () => Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>,
  base: string,
  context: ShiftContext,
): TransferJournal {
  const key = JSON.stringify([
    'relay-transfer-v1', base, context.outgoingShiftId, context.incomingShiftId, context.incomingOperatorId,
  ])
  return {
    read() {
      const raw = storage().getItem(key)
      if (raw === null) return undefined
      const value: unknown = JSON.parse(raw)
      if (typeof value !== 'object' || value === null) throw new Error('Invalid transfer state.')
      if ('kind' in value && value.kind === 'receipt' && 'receiptId' in value && uuid(value.receiptId)) {
        return { kind: 'receipt', receiptId: value.receiptId }
      }
      if ('kind' in value && value.kind === 'pending' && 'handoverId' in value && uuid(value.handoverId)
        && 'command' in value && typeof value.command === 'object' && value.command !== null) {
        const command = value.command as Partial<AcceptCommand>
        if (uuid(command.operation_id) && command.actor_id === context.incomingOperatorId
          && typeof command.expected_version === 'number' && Number.isSafeInteger(command.expected_version)
          && command.expected_version > 0 && command.confirmed === true) {
          return {
            kind: 'pending', handoverId: value.handoverId,
            command: {
              operation_id: command.operation_id, actor_id: command.actor_id,
              expected_version: command.expected_version, confirmed: true,
            },
          }
        }
      }
      throw new Error('Invalid transfer state.')
    },
    write(entry) {
      if (entry) storage().setItem(key, JSON.stringify(entry))
      else storage().removeItem(key)
    },
  }
}
