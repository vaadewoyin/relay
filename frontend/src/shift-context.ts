export type ShiftContext = {
  outgoingShiftId: string
  incomingShiftId: string
  outgoingOperatorId: string
  incomingOperatorId: string
  incomingName: string
  shiftLabel: string
}

const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i

export function parseShiftContext(raw: unknown): ShiftContext | undefined {
  if (typeof raw !== 'string') return undefined
  try {
    const data = JSON.parse(raw) as Partial<ShiftContext> | null
    if (!data || typeof data !== 'object') return undefined
    const { outgoingShiftId, incomingShiftId, outgoingOperatorId, incomingOperatorId,
      incomingName, shiftLabel } = data
    if (
      typeof outgoingShiftId !== 'string' || !uuid.test(outgoingShiftId)
      || typeof incomingShiftId !== 'string' || !uuid.test(incomingShiftId)
      || typeof outgoingOperatorId !== 'string' || !uuid.test(outgoingOperatorId)
      || typeof incomingOperatorId !== 'string' || !uuid.test(incomingOperatorId)
      || typeof incomingName !== 'string' || !incomingName.trim()
      || typeof shiftLabel !== 'string' || !shiftLabel.trim()
    ) return undefined
    return { outgoingShiftId, incomingShiftId, outgoingOperatorId, incomingOperatorId,
      incomingName, shiftLabel }
  } catch {
    return undefined
  }
}
