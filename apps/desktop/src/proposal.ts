import type { Proposal, ProposalCategory, ProposalExample, RuleKind } from './types'

/** A category being reviewed. `sources` are the engine category ids it was built from. */
export interface DraftCategory {
  id: string
  kind: RuleKind
  name: string
  folderName: string
  description?: string | null
  count: number
  examples: ProposalExample[]
  confidence: ProposalCategory['confidence']
  splittable: boolean
  sources: string[]
}

export interface Draft {
  analysisId: string
  categories: DraftCategory[]
  other: { count: number; examples: ProposalExample[] }
  /** file index -> category id or 'other' */
  moves: Record<string, string>
}

export const OTHER = 'other'

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value))

export function toDraftCategory(category: ProposalCategory): DraftCategory {
  return { ...clone(category), sources: [category.id] }
}

export function draftFromProposal(proposal: Proposal): Draft {
  return {
    analysisId: proposal.analysisId,
    categories: proposal.categories.map(toDraftCategory),
    other: clone(proposal.other),
    moves: {},
  }
}

export function rename(draft: Draft, id: string, name: string, folderName?: string): Draft {
  const next = clone(draft)
  const category = next.categories.find((item) => item.id === id)
  if (category) {
    if (folderName === undefined && category.folderName === category.name) category.folderName = name
    category.name = name
    if (folderName !== undefined) category.folderName = folderName
  }
  return next
}

export function canMerge(draft: Draft, ids: string[]): boolean {
  const chosen = draft.categories.filter((item) => ids.includes(item.id))
  return chosen.length >= 2 && new Set(chosen.map((item) => item.kind)).size === 1
}

/** Merge several categories of the same kind into the first one selected (in list order). */
export function merge(draft: Draft, ids: string[]): Draft {
  if (!canMerge(draft, ids)) return draft
  const next = clone(draft)
  const chosen = next.categories.filter((item) => ids.includes(item.id))
  const [first, ...rest] = chosen
  for (const item of rest) {
    first.count += item.count
    first.sources.push(...item.sources)
    first.examples = [...first.examples, ...item.examples].slice(0, 5)
    for (const level of ['high', 'medium', 'low'] as const) first.confidence[level] += item.confidence[level]
  }
  first.splittable = false
  for (const [index, target] of Object.entries(next.moves)) if (rest.some((item) => item.id === target)) next.moves[index] = first.id
  next.categories = next.categories.filter((item) => !rest.includes(item))
  return next
}

/** Remove a category: its files go to Other / Unsorted. */
export function remove(draft: Draft, id: string): Draft {
  const next = clone(draft)
  const category = next.categories.find((item) => item.id === id)
  if (!category) return draft
  next.other.count += category.count
  next.other.examples = [...next.other.examples, ...category.examples].slice(0, 5)
  for (const [index, target] of Object.entries(next.moves)) if (target === id) next.moves[index] = OTHER
  next.categories = next.categories.filter((item) => item.id !== id)
  return next
}

/** Move one example file to another category (or 'other'). */
export function moveExample(draft: Draft, index: number, from: string, to: string): Draft {
  if (from === to) return draft
  const next = clone(draft)
  const source = from === OTHER ? next.other : next.categories.find((item) => item.id === from)
  const target = to === OTHER ? next.other : next.categories.find((item) => item.id === to)
  if (!source || !target) return draft
  const example = source.examples.find((item) => item.index === index)
  if (!example) return draft
  source.examples = source.examples.filter((item) => item.index !== index)
  source.count = Math.max(0, source.count - 1)
  target.examples = [example, ...target.examples].slice(0, 5)
  target.count += 1
  next.moves[String(index)] = to
  return next
}

/** Replace a split category with the categories the engine returned. */
export function applySplit(draft: Draft, proposal: Proposal): Draft {
  if (!proposal.replaced) return draft
  const next = clone(draft)
  const position = next.categories.findIndex((item) => item.sources.includes(proposal.replaced!))
  if (position < 0) return draft
  const created = proposal.categories.filter((item) => proposal.created?.includes(item.id)).map(toDraftCategory)
  next.categories.splice(position, 1, ...created)
  for (const [index, target] of Object.entries(next.moves)) if (target === draft.categories[position].id) delete next.moves[index]
  return next
}

export interface DraftIssue { id?: string; message: string }

export function draftIssues(draft: Draft, maxCategories = 12): DraftIssue[] {
  const issues: DraftIssue[] = []
  if (!draft.categories.length) issues.push({ message: 'Keep at least one category' })
  if (draft.categories.length > maxCategories) issues.push({ message: `At most ${maxCategories} categories` })
  const seen = new Map<string, string>()
  for (const item of draft.categories) {
    if (!item.name.trim()) issues.push({ id: item.id, message: 'Name cannot be empty' })
    const key = item.folderName.trim().toLocaleLowerCase()
    if (!key || /[/\\<>:"|?*\u0000-\u001f]/.test(item.folderName) || /[. ]$/.test(item.folderName) || ['.', '..'].includes(key)) issues.push({ id: item.id, message: 'Folder name is invalid' })
    else if (seen.has(key)) issues.push({ id: item.id, message: `Folder name is already used by “${seen.get(key)}”` })
    else seen.set(key, item.name)
  }
  return issues
}

export function acceptPayload(draft: Draft) {
  return {
    analysisId: draft.analysisId,
    categories: draft.categories.map((item) => ({ id: item.id, name: item.name.trim(), folderName: item.folderName.trim(), description: item.description ?? undefined, sources: item.sources })),
    moves: draft.moves,
  }
}

export function confidenceSpread(category: Pick<DraftCategory, 'confidence' | 'count'>): Array<{ level: 'high' | 'medium' | 'low'; share: number }> {
  const total = Math.max(1, category.confidence.high + category.confidence.medium + category.confidence.low)
  return (['high', 'medium', 'low'] as const).map((level) => ({ level, share: category.confidence[level] / total }))
}
