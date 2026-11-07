export type ViewName =
  | 'onboarding'
  | 'home'
  | 'analyze'
  | 'config'
  | 'scan'
  | 'preview'
  | 'duplicates'
  | 'executing'
  | 'result'
  | 'history'
  | 'undo'
  | 'quarantine'
  | 'settings'
  | 'about'

export type PresetType = 'by-type' | 'by-date' | 'old-installers' | 'duplicates'

export interface Preset {
  id: PresetType
  name: string
  description: string
  operation: 'move' | 'quarantine'
}

export interface Profile {
  id: string
  name: string
  presetType: PresetType
  sourceFolders: string[]
  targetFolder: string
  includeSubfolders: boolean
  parameters: {
    categories?: string[]
    olderThanDays?: number
    includeArchives?: boolean
    minimumBytes?: number
    dateSource?: 'taken' | 'modified'
    typeRules?: TypeRule[]
    unmatchedAction?: 'other' | 'keep'
    otherFolder?: string
  }
  schemaVersion: number
}

export type RuleKind = 'extension' | 'metadata' | 'content'

export interface MetadataMatch {
  isScreenshot?: boolean
  hasCamera?: boolean
  isScan?: boolean
  minPixels?: number
  dateTakenRange?: [string | null, string | null]
  anyOf?: MetadataMatch[]
}

export interface TypeRule {
  id: string
  name: string
  folderName: string
  extensions: string[]
  enabled: boolean
  kind?: RuleKind
  match?: MetadataMatch
  centroidRef?: string
  description?: string
}

export type Confidence = 'high' | 'medium' | 'low'

export interface InventorySummary {
  files: number
  bytes: number
  families: Record<string, number>
  topExtensions: Array<{ extension: string; count: number }>
  photos: number
  screenshots: number
  withDateTaken: number
  withLocation: number
}

export interface ProposalExample { index: number; name: string }

export interface ProposalCategory {
  id: string
  kind: RuleKind
  name: string
  folderName: string
  description?: string | null
  count: number
  examples: ProposalExample[]
  confidence: Record<Confidence, number>
  splittable: boolean
}

export interface Proposal {
  analysisId: string
  mode: 'ai' | 'heuristic'
  notice?: 'AI_DISABLED' | 'AI_UNAVAILABLE' | 'NAMING_FALLBACK' | null
  tooFew: boolean
  total: number
  categories: ProposalCategory[]
  other: { count: number; examples: ProposalExample[] }
  maxCategories: number
  created?: string[]
  replaced?: string
}

export interface ClassifierStatus {
  aiEnabled: boolean
  ollamaInstalled: boolean
  vectorBackend: string
  maxCategories: number
  models: string[] | null
  embedModelInstalled: boolean | null
  llmModelInstalled: boolean | null
  error: string | null
}

export interface Settings {
  theme: 'system' | 'light' | 'dark'
  retentionDays: number
  historyLimit: number
  redactPaths: boolean
  notifyOnComplete: boolean
  defaultTargetFolder: string
  quarantineFolder: string
  aiEnabled: boolean
  aiEmbedModel: string
  aiLlmModel: string
  aiDescriptions: boolean
  aiThreshold: number
  aiOcr: boolean
}

export interface PlanItem {
  itemId: string
  sequence: number
  groupId?: string | null
  operation: 'move' | 'quarantine' | 'skip'
  sourcePath: string
  targetPath?: string | null
  size: number
  selected: boolean
  status: string
  warningCode?: string | null
  reason?: string | null
  metadata: Record<string, unknown>
}

export interface PlanSummary {
  total: number
  selected: number
  selectedBytes: number
  move: number
  quarantine: number
  skip: number
  conflict: number
  groups: number
  suggestions?: number
  fromAnalysisId?: string
  aiNotice?: string
}

export interface Plan {
  planId: string
  status: string
  createdAt: string
  expiresAt: string
  profile: Profile
  summary: PlanSummary
  items: PlanItem[]
}

export interface RunResult {
  runId: string
  planId: string
  status: 'completed' | 'partial' | 'cancelled' | 'failed'
  total: number
  success: number
  skipped: number
  failed: number
  successBytes?: number
  endedAt: string
}

export interface HistoryRun {
  run_id: string
  plan_id: string
  profile: Profile
  status: RunResult['status']
  total: number
  success: number
  skipped: number
  failed: number
  started_at: string
  ended_at?: string
  undoable_count: number
}

export interface HistoryOperation {
  operation_id: string
  operation: 'move' | 'quarantine'
  source_path: string
  target_path: string
  state: 'started' | 'applied' | 'failed' | 'undone' | 'skipped'
  error_code?: string | null
  error_detail?: string | null
}

export interface HistoryDetail extends HistoryRun {
  operations: HistoryOperation[]
}

export interface QuarantineItem {
  quarantine_id: string
  operation_id: string
  original_path: string
  quarantine_path: string
  reason: string
  size: number
  quarantined_at: string
  retention_until: string
  status: string
}

export interface UndoItem {
  operationId: string
  currentPath: string
  restorePath: string
  size: number
  state: 'ready' | 'rename' | 'changed' | 'missing'
  selected: boolean
}

export interface UndoPreview {
  runId: string
  items: UndoItem[]
}

export interface EngineEvent {
  event: string
  payload: Record<string, unknown>
}
