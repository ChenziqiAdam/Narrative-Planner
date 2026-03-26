import relationLexiconJson from '../data/relationLexicon.json'

export type RelationGroupKey = 'family' | 'friend' | 'work' | 'other'

type RelationMeta = {
  label: string
  group: Exclude<RelationGroupKey, 'other'>
  aliases: string[]
  patterns: string[]
}

type RelationLexicon = {
  groupLabels: Record<RelationGroupKey, string>
  normalizationPrefixes: string[]
  selfReferences: string[]
  groupPatterns: Record<Exclude<RelationGroupKey, 'other'>, string[]>
  relations: Record<string, RelationMeta>
}

const relationLexicon = relationLexiconJson as RelationLexicon

const PUNCTUATION_REGEX =
  /[\s\u3000·•．。,.，、:：;；!！?？"'“”‘’()（）[\]{}<>《》【】\-—_]/gu

const normalizedPrefixes = relationLexicon.normalizationPrefixes
  .map(prefix => prefix.toLowerCase())
  .sort((left, right) => right.length - left.length)

const normalizedSelfReferences = new Set(
  relationLexicon.selfReferences.map(reference => normalizeRelationSignal(reference)),
)

const relationEntries = Object.entries(relationLexicon.relations).map(([code, meta]) => ({
  code,
  ...meta,
  normalizedAliases: meta.aliases
    .map(alias => normalizeRelationSignal(alias))
    .filter(Boolean)
    .sort((left, right) => right.length - left.length),
  compiledPatterns: meta.patterns.map(pattern => new RegExp(pattern, 'iu')),
}))

const groupPatternEntries = Object.entries(relationLexicon.groupPatterns).map(([group, patterns]) => ({
  group: group as Exclude<RelationGroupKey, 'other'>,
  compiledPatterns: patterns.map(pattern => new RegExp(pattern, 'iu')),
}))

export function normalizeRelationSignal(value: string): string {
  let normalized = (value || '').trim().toLowerCase()
  if (!normalized) return ''

  normalized = normalized.replace(PUNCTUATION_REGEX, '')

  for (const prefix of normalizedPrefixes) {
    if (normalized.startsWith(prefix)) {
      normalized = normalized.slice(prefix.length)
      break
    }
  }

  return normalized
}

export function isSelfReference(value: string): boolean {
  return normalizedSelfReferences.has(normalizeRelationSignal(value))
}

export function inferRelationCode(value: string): string | null {
  const rawValue = (value || '').trim()
  const normalized = normalizeRelationSignal(rawValue)
  if (!normalized) return null

  for (const entry of relationEntries) {
    if (entry.normalizedAliases.includes(normalized)) {
      return entry.code
    }
  }

  for (const entry of relationEntries) {
    if (
      entry.normalizedAliases.some(alias => alias.length >= 2 && normalized.includes(alias))
      || entry.compiledPatterns.some(pattern => pattern.test(rawValue) || pattern.test(normalized))
    ) {
      return entry.code
    }
  }

  return null
}

export function getRelationLabel(codeOrRaw: string | null | undefined): string {
  const relationValue = (codeOrRaw || '').trim()
  if (!relationValue) return '关系待补充'

  const directMatch = relationLexicon.relations[relationValue]
  if (directMatch) return directMatch.label

  const inferredCode = inferRelationCode(relationValue)
  if (inferredCode && relationLexicon.relations[inferredCode]) {
    return relationLexicon.relations[inferredCode].label
  }

  if (relationValue in relationLexicon.groupLabels) {
    return relationLexicon.groupLabels[relationValue as RelationGroupKey]
  }

  return relationValue
}

export function getRelationGroup(
  values: Array<string | null | undefined>,
  explicitRelation?: string | null,
): RelationGroupKey {
  const relationCode = inferRelationCode(explicitRelation || '')
  if (relationCode) {
    return relationLexicon.relations[relationCode].group
  }

  const mergedRawValue = values.filter(Boolean).join(' ')
  const normalized = normalizeRelationSignal(mergedRawValue)
  if (!normalized) return 'other'

  const inferredFromSignals = inferRelationCode(mergedRawValue)
  if (inferredFromSignals) {
    return relationLexicon.relations[inferredFromSignals].group
  }

  for (const { group, compiledPatterns } of groupPatternEntries) {
    if (compiledPatterns.some(pattern => pattern.test(mergedRawValue) || pattern.test(normalized))) {
      return group
    }
  }

  return 'other'
}

export function getRelationGroupLabel(group: RelationGroupKey): string {
  return relationLexicon.groupLabels[group]
}
