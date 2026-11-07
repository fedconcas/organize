export type ViewName =
  | 'onboarding'
  | 'home'
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

export interface TypeRule {
  id: string
  name: string
  folderName: string
  extensions: string[]
  enabled: boolean
}

export interface Settings {
  theme: 'system' | 'light' | 'dark'
  retentionDays: number
  historyLimit: number
  redactPaths: boolean
  notifyOnComplete: boolean
  defaultTargetFolder: string
  quarantineFolder: string
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
