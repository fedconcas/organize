import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'

const load = async (file) => {
  const source = await readFile(new URL(`../src/${file}`, import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
}
const P = await load('proposal.ts')
const { ruleIssues, hasAiRules } = await load('profiles.ts')

const category = (id, kind, count, names = [], extra = {}) => ({
  id, kind, name: `Cat ${id}`, folderName: `Cat ${id}`, description: null, count,
  examples: names.map((name, index) => ({ index: Number(id.slice(1)) * 10 + index, name })),
  confidence: { high: count, medium: 0, low: 0 }, splittable: kind === 'content', ...extra,
})
const proposal = () => ({
  analysisId: 'a1', mode: 'ai', notice: null, tooFew: false, total: 40, maxCategories: 12,
  categories: [category('c1', 'content', 10, ['a.pdf', 'b.pdf']), category('c2', 'content', 6, ['c.txt']), category('c3', 'metadata', 5, ['IMG_1.jpg'])],
  other: { count: 4, examples: [{ index: 99, name: 'x.bin' }] },
})

test('rename keeps a matching folder name in sync and edits are immutable', () => {
  const draft = P.draftFromProposal(proposal())
  const renamed = P.rename(draft, 'c1', 'Invoices')
  assert.equal(renamed.categories[0].name, 'Invoices')
  assert.equal(renamed.categories[0].folderName, 'Invoices')
  assert.equal(draft.categories[0].name, 'Cat c1')
  const custom = P.rename(renamed, 'c1', 'Invoices', 'Bills')
  assert.equal(P.rename(custom, 'c1', 'Receipts').categories[0].folderName, 'Bills')
})

test('merge combines same-kind categories and refuses mixed kinds', () => {
  const draft = P.draftFromProposal(proposal())
  assert.equal(P.canMerge(draft, ['c1', 'c3']), false)
  assert.equal(P.merge(draft, ['c1', 'c3']), draft)
  const merged = P.merge(draft, ['c2', 'c1'])
  assert.equal(merged.categories.length, 2)
  assert.deepEqual(merged.categories[0].sources, ['c1', 'c2'])
  assert.equal(merged.categories[0].count, 16)
  assert.equal(merged.categories[0].confidence.high, 16)
  assert.equal(merged.categories[0].splittable, false)
})

test('remove sends files to Other and moves re-target', () => {
  let draft = P.draftFromProposal(proposal())
  draft = P.moveExample(draft, 30, 'c3', 'c2')
  assert.equal(draft.moves['30'], 'c2')
  assert.equal(draft.categories[1].count, 7)
  assert.equal(draft.categories[2].count, 4)
  draft = P.remove(draft, 'c2')
  assert.equal(draft.other.count, 11)
  assert.equal(draft.moves['30'], 'other')
  assert.equal(P.moveExample(draft, 12345, 'c1', 'other'), draft)
})

test('split replaces the category with the engine result, keeping other edits', () => {
  let draft = P.rename(P.draftFromProposal(proposal()), 'c2', 'Notes')
  draft = P.moveExample(draft, 10, 'c1', 'c2')
  const result = { ...proposal(), replaced: 'c1', created: ['c7', 'c8'],
    categories: [category('c2', 'content', 6), category('c3', 'metadata', 5), category('c7', 'content', 5), category('c8', 'content', 4)] }
  const split = P.applySplit(draft, result)
  assert.deepEqual(split.categories.map((item) => item.id), ['c7', 'c8', 'c2', 'c3'])
  assert.equal(split.categories[2].name, 'Notes')
  assert.equal(split.moves['10'], 'c2')
})

test('draft issues catch empty names, bad and duplicate folders and the cap', () => {
  let draft = P.draftFromProposal(proposal())
  assert.deepEqual(P.draftIssues(draft), [])
  draft = P.rename(draft, 'c1', '', 'a/b')
  draft = P.rename(draft, 'c2', 'X', 'cat C3')
  const messages = P.draftIssues(draft).map((issue) => `${issue.id}:${issue.message}`)
  assert.ok(messages.includes('c1:Name cannot be empty'))
  assert.ok(messages.includes('c1:Folder name is invalid'))
  assert.ok(messages.some((item) => item.startsWith('c3:Folder name is already used')))
  assert.ok(P.draftIssues(draft, 2).some((issue) => issue.message === 'At most 2 categories'))
  const payload = P.acceptPayload(P.draftFromProposal(proposal()))
  assert.deepEqual(payload.categories.map((item) => item.sources), [['c1'], ['c2'], ['c3']])
})

test('content and metadata rules validate without extension conflicts', () => {
  const profile = { parameters: { unmatchedAction: 'other', otherFolder: 'Other files', typeRules: [
    { id: 'a', name: 'Invoices', folderName: 'Invoices', extensions: [], enabled: true, kind: 'content', centroidRef: 'r' },
    { id: 'b', name: 'Screens', folderName: 'Screens', extensions: ['png', 'jpg'], enabled: true, kind: 'metadata', match: { isScreenshot: true } },
    { id: 'c', name: 'Camera', folderName: 'Camera', extensions: ['jpg'], enabled: true, kind: 'metadata', match: { hasCamera: true } },
    { id: 'd', name: 'Images', folderName: 'Images', extensions: ['jpg'], enabled: true },
  ] } }
  assert.deepEqual(ruleIssues(profile), [])
  assert.equal(hasAiRules(profile), true)
  profile.parameters.typeRules.push({ id: 'e', name: 'More', folderName: 'More', extensions: ['jpg'], enabled: true })
  assert.equal(ruleIssues(profile).length, 1)
})
