import type { Profile, TypeRule } from './types'

const rule = (id: string, name: string, extensions: string): TypeRule => ({
  id, name, folderName: name, extensions: extensions.split(' '), enabled: true,
})
export function classificationTemplate(template = 'standard'): TypeRule[] {
  if (template === 'office') return [
    rule('text', 'Text documents', 'doc docx txt md'), rule('pdf', 'PDFMaterials', 'pdf'),
    rule('sheets', 'Spreadsheets', 'xls xlsx csv'), rule('slides', 'Presentations', 'ppt pptx'),
  ]
  if (template === 'media') return [
    rule('photos', 'Photos', 'jpg jpeg heic tif tiff'), rule('graphics', 'Graphics', 'png gif webp svg psd ai'),
    rule('videos', 'Videos', 'mp4 mov mkv avi webm m4v'), rule('audio', 'Audio', 'mp3 m4a wav flac aac ogg'),
  ]
  return [rule('documents', 'Documents', 'pdf doc docx xls xlsx ppt pptx txt md csv'),
    rule('images', 'Images', 'jpg jpeg png gif webp heic tif tiff'),
    rule('videos', 'Videos', 'mp4 mov mkv avi webm m4v'), rule('audio', 'Audio', 'mp3 m4a wav flac aac ogg'),
    rule('archives', 'Archives', 'zip 7z rar tar gz bz2 xz'), rule('installers', 'Installers', 'exe msi msix dmg pkg')]
}

export const CLASSIFICATION_TEMPLATES = [
  { id: 'standard', name: 'General', description: 'Documents, images, videos, audio, archives, installers' },
  { id: 'office', name: 'Office documents', description: 'Text documents, PDFs, spreadsheets and presentations kept apart' },
  { id: 'media', name: 'Media', description: 'Photos, graphics, videos, audio' },
] as const

export function ensureClassification(profile: Profile) {
  if (!profile.parameters.typeRules) {
    profile.parameters.typeRules = classificationTemplate().map((rule) => ({ ...rule,
      enabled: !profile.parameters.categories || profile.parameters.categories.includes(rule.id),
    }))
    profile.parameters.unmatchedAction = !profile.parameters.categories || profile.parameters.categories.includes('other') ? 'other' : 'keep'
    profile.parameters.otherFolder = 'Other files'
  }
}

export function parseExtensions(value: string): string[] {
  return value.split(/[\s,;\uFF0C\u3001\uFF1B]+/).map((part) => part.replace(/^\.+/, '').toLowerCase()).filter(Boolean)
}

export function newRuleName(rules: TypeRule[]): string {
  const names = new Set(rules.map((item) => item.name))
  if (!names.has('New category')) return 'New category'
  let index = 2
  while (names.has(`New category ${index}`)) index++
  return `New category ${index}`
}

// Mirrors engine/src/organize_gui/profiles.py so problems show while editing, before profile.validate.
export function validFolderName(value: unknown): boolean {
  return typeof value === 'string'
    && Boolean(value.trim())
    && !['.', '..'].includes(value.trim())
    && value.length <= 120
    && !/[/\\<>:"|?*\u0000-\u001f]/.test(value)
    && !/[. ]$/.test(value)
}

const EXTENSION = /^[a-z0-9][a-z0-9_+-]*$/

export function validExtension(value: string): boolean {
  return EXTENSION.test(value)
}

export interface RuleIssue {
  ruleId?: string
  field: 'name' | 'folder' | 'extensions' | 'other' | 'rules'
  message: string
}

/** Extension → names of the enabled rules that claim it, in rule order. */
export function extensionOwners(rules: TypeRule[]): Map<string, string[]> {
  const owners = new Map<string, string[]>()
  for (const item of rules) {
    if (!item.enabled) continue
    for (const extension of new Set(item.extensions)) owners.set(extension, [...(owners.get(extension) ?? []), item.name || 'Unnamed category'])
  }
  return owners
}

export function ruleIssues(profile: Profile): RuleIssue[] {
  const rules = profile.parameters.typeRules ?? []
  const issues: RuleIssue[] = []
  const claimed = new Map<string, string>()
  for (const item of rules) {
    if (!item.enabled) continue
    if (!item.name.trim()) issues.push({ ruleId: item.id, field: 'name', message: 'Category name cannot be empty' })
    if (!validFolderName(item.folderName)) issues.push({ ruleId: item.id, field: 'folder', message: 'Subfolder name cannot be empty or contain / \\ : * ? " < > |' })
    if (!item.extensions.length) issues.push({ ruleId: item.id, field: 'extensions', message: 'Add at least one extension' })
    for (const extension of item.extensions) {
      if (!validExtension(extension)) issues.push({ ruleId: item.id, field: 'extensions', message: `“${extension}” is not a valid extension` })
      else if (claimed.has(extension)) issues.push({ ruleId: item.id, field: 'extensions', message: `“${extension}” already belongs to “${claimed.get(extension)}”` })
      else claimed.set(extension, item.name || 'Unnamed category')
    }
  }
  const unmatched = profile.parameters.unmatchedAction ?? 'other'
  if (unmatched === 'other' && !validFolderName(profile.parameters.otherFolder)) issues.push({ field: 'other', message: 'The “Other” folder name is invalid' })
  if (!rules.some((item) => item.enabled) && unmatched !== 'other') issues.push({ field: 'rules', message: 'Enable at least one category, or put unmatched files into the Other folder' })
  return issues
}

/** JSON with sorted keys, so a profile round-tripped through the engine compares equal. */
export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().filter((key) => (value as Record<string, unknown>)[key] !== undefined)
      .map((key) => `${JSON.stringify(key)}:${stableStringify((value as Record<string, unknown>)[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}
