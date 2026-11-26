import type { Finding, SourceReport } from './api.ts'

export const findingTitles: Record<Finding['type'], string> = {
  missing_owner: 'Missing action owner',
  overdue_action: 'Overdue action',
  duplicate_report: 'Duplicate report',
  stale_version: 'Stale record',
  unresolved_responsibility: 'Unresolved responsibility',
  contradictory_asset_status: 'Conflicting asset status',
  semantic_contradiction: 'Conflicting reports',
  unsupported_completion: 'Unverified completion',
  ambiguous_ownership: 'Ambiguous ownership',
  missing_operational_context: 'Missing context',
  unresolved_safety_concern: 'Open safety concern',
  inconsistent_completion: 'Conflicting completion',
  potential_duplicate_incident: 'Possible duplicate incident',
}

const severityOrder = { high: 0, warning: 1, info: 2 }

export function orderFindings(findings: readonly Finding[]): Finding[] {
  return [...findings].sort((a, b) =>
    Number(b.review_status === 'pending') - Number(a.review_status === 'pending')
    || severityOrder[a.severity] - severityOrder[b.severity]
    || Date.parse(a.created_at) - Date.parse(b.created_at)
    || a.id.localeCompare(b.id),
  )
}

export function wrapText(text: string, width = 42): string[] {
  const lines: string[] = []
  let line = ''
  for (const word of text.trim().split(/\s+/)) {
    for (const part of word.match(new RegExp(`.{1,${width}}`, 'gu')) ?? []) {
      const candidate = line ? `${line} ${part}` : part
      if (Array.from(candidate).length <= width) {
        line = candidate
      } else {
        lines.push(line)
        line = part
      }
    }
  }
  if (line) lines.push(line)
  return lines
}

export function clip(text: string, width = 42): string {
  const characters = Array.from(text.trim().replace(/\s+/g, ' '))
  return characters.length > width ? `${characters.slice(0, width - 3).join('')}...` : characters.join('')
}

export const tagline = 'Nothing gets lost between shifts.'

export function excerpt(text: string, maxLines: number): string[] {
  const lines = wrapText(text)
  if (lines.length <= maxLines) return lines
  return [...lines.slice(0, maxLines - 1), Array.from(lines[maxLines - 1]).slice(0, 39).join('').trimEnd() + '...']
}

export function display(title: string, body: string[], hint: string): string {
  // Ten text lines exceed the framebuffer and hand scrolling over to the SDK.
  const spacer = body.length <= 6 ? [''] : []
  return [title, ...body, ...spacer, hint].join('\n')
}

export function menu(choices: string[], cursor: number): string[] {
  return choices.map((choice, index) => `${index === cursor ? '>' : ' '} ${clip(choice, 40)}`)
}

export function itemPages<T extends { description: string }>(items: readonly T[]) {
  return items.flatMap((item, index) => {
    const lines = wrapText(item.description)
    const pages = Math.ceil(lines.length / 3)
    return Array.from({ length: pages }, (_, page) => ({
      item, index, lines: lines.slice(page * 3, page * 3 + 3),
      suffix: pages > 1 ? ` | Page ${page + 1}/${pages}` : '',
    }))
  })
}

export type EvidencePage = { heading: string; source: string; status: string; lines: string[] }

export function evidencePages(source: SourceReport, index: number, count: number, quote: string): EvidencePage[] {
  const lines = wrapText(quote)
  const pageCount = Math.ceil(lines.length / 4)
  const time = source.observed_at ? new Date(source.observed_at).toISOString().slice(11, 16) + ' UTC' : ''
  const notion = source.source_url && source.source_ref.startsWith('notion:')
  const reference = notion ? 'Notion | ' + source.source_ref.slice(-8).toUpperCase() : source.source_ref
  const status = source.asset_status?.replaceAll('_', ' ') ?? 'Report excerpt'
  return Array.from({ length: pageCount }, (_, page) => ({
    heading: `Source ${index + 1}/${count}${pageCount > 1 ? ` | ${page + 1}/${pageCount}` : ''}`,
    source: clip(reference),
    status: time ? `${time} | ${status}` : status,
    lines: lines.slice(page * 4, page * 4 + 4),
  }))
}
