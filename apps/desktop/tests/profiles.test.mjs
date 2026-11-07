import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'

const source = await readFile(new URL('../src/profiles.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
const { classificationTemplate, ensureClassification, parseExtensions, ruleIssues, validFolderName, extensionOwners, newRuleName, stableStringify } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('each template is independently editable with unambiguous extensions', () => {
  for (const template of ['standard', 'office', 'media']) {
    const rules = classificationTemplate(template)
    const extensions = rules.flatMap(rule => rule.extensions)
    assert.equal(new Set(extensions).size, extensions.length)
    rules[0].folderName = 'custom'
    assert.notEqual(classificationTemplate(template)[0].folderName, 'custom')
  }
})
test('legacy categories retain enabled and unmatched choices', () => {
  const profile = { parameters: { categories: ['images'] } }
  ensureClassification(profile)
  assert.deepEqual(profile.parameters.typeRules.filter(rule => rule.enabled).map(rule => rule.id), ['images'])
  assert.equal(profile.parameters.unmatchedAction, 'keep')
})
test('custom saved rules are not overwritten', () => {
  const rules = [{ id: 'custom', folderName: '素材', extensions: ['psd'] }]
  const profile = { parameters: { typeRules: rules } }
  ensureClassification(profile)
  assert.equal(profile.parameters.typeRules, rules)
})
test('extension entry accepts dots, mixed case and Chinese separators', () => {
  assert.deepEqual(parseExtensions('.PDF， DOCX、.md; png jpg'), ['pdf','docx','md','png','jpg'])
})
const byType = (typeRules, extra = {}) => ({ parameters: { typeRules, unmatchedAction: 'other', otherFolder: '其他文件', ...extra } })
test('standard template has no rule issues', () => {
  assert.deepEqual(ruleIssues(byType(classificationTemplate())), [])
})
test('folder names follow the engine rules', () => {
  for (const bad of ['', ' ', '.', '..', 'a/b', 'a\\b', 'a:b', 'end.', 'end ', 'x'.repeat(121), 'tab\tx']) assert.equal(validFolderName(bad), false, bad)
  for (const good of ['文档', 'Photos 2026', 'a.b']) assert.equal(validFolderName(good), true, good)
})
test('duplicate extension is reported on the later enabled rule only', () => {
  const rules = classificationTemplate()
  rules[1].extensions.push('pdf')
  const issues = ruleIssues(byType(rules))
  assert.deepEqual(issues.map(issue => [issue.ruleId, issue.field]), [['images', 'extensions']])
  assert.match(issues[0].message, /pdf.*Documents/)
  assert.deepEqual(extensionOwners(rules).get('pdf'), ['Documents', 'Images'])
  rules[1].enabled = false
  assert.deepEqual(ruleIssues(byType(rules)), [])
})
test('empty name, bad folder, missing and invalid extensions are flagged per field', () => {
  const fields = ruleIssues(byType([{ id: 'x', name: ' ', folderName: 'a/b', extensions: [], enabled: true }])).map(issue => issue.field)
  assert.deepEqual(fields, ['name', 'folder', 'extensions'])
  assert.equal(ruleIssues(byType([{ id: 'y', name: 'n', folderName: 'n', extensions: ['-bad'], enabled: true }]))[0].field, 'extensions')
})
test('unmatched handling: invalid other folder and no categories', () => {
  assert.deepEqual(ruleIssues(byType([], { otherFolder: '..' })).map(issue => issue.field), ['other'])
  assert.deepEqual(ruleIssues(byType([], { unmatchedAction: 'keep' })).map(issue => issue.field), ['rules'])
})
test('new rule names stay unique and stable stringify ignores key order', () => {
  assert.equal(newRuleName([{ name: 'New category' }, { name: 'New category 2' }]), 'New category 3')
  assert.equal(stableStringify({ b: 1, a: [{ d: 1, c: 2 }] }), stableStringify({ a: [{ c: 2, d: 1 }], b: 1 }))
})
