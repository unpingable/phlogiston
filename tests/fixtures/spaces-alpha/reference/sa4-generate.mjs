#!/usr/bin/env node

import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const PINNED_COMMIT = '89deb9faca20e56fa2a262fe9746ed52bc1095ba'
const FORMAT = 'spaces-alpha-sa4-reference-transition-vector-v1'
const SOURCE_FORMAT = 'spaces-alpha-sa4-source-vector-v1'
const LOCAL_TRANSITION_VERSION = 'sa4-v1'
const EXPECTED_TRANSITION_RECEIPTS = {
  'n-to-n1':
    'sha256:55a0adf0522c47333b174c0071f8dc7a99f5239182c5ccbdc810760a7c92337f',
  'n1-to-n2':
    'sha256:6bd6827ac83a780f0ea852ba08da80e5a293a381366a56d362eca8d1f952e526',
}

const [referenceArgument, sourceArgument, outputDirectoryArgument, manifestArgument] =
  process.argv.slice(2)
if (
  !referenceArgument ||
  !sourceArgument ||
  !outputDirectoryArgument ||
  !manifestArgument
) {
  throw new Error(
    'usage: sa4-generate.mjs <pinned-atproto-worktree> <source-json> ' +
      '<car-output-directory> <manifest-json>',
  )
}

const referenceRoot = resolve(referenceArgument)
const sourcePath = resolve(sourceArgument)
const outputDirectory = resolve(outputDirectoryArgument)
const manifestPath = resolve(manifestArgument)
const head = execFileSync('git', ['-C', referenceRoot, 'rev-parse', 'HEAD'], {
  encoding: 'utf8',
}).trim()
if (head !== PINNED_COMMIT) {
  throw new Error(`reference worktree is ${head}, expected ${PINNED_COMMIT}`)
}

const loadReferenceModule = (relative) =>
  import(pathToFileURL(join(referenceRoot, relative)).href)
const [
  { readCarStream },
  { decode },
  { parseCid },
  { RepoCommit, serializeRepo },
] = await Promise.all([
  loadReferenceModule('packages/common/dist/index.js'),
  loadReferenceModule('packages/lex/lex-cbor/dist/index.js'),
  loadReferenceModule('packages/lex/lex-data/dist/index.js'),
  loadReferenceModule('packages/space/dist/index.js'),
])

const sourceBytes = await readFile(sourcePath)
const source = JSON.parse(sourceBytes.toString('utf8'))
if (source.format !== SOURCE_FORMAT) throw new Error('unexpected SA4 source format')
if (source.compatibility.referenceCommit !== PINNED_COMMIT) {
  throw new Error('SA4 source uses another reference commit')
}

const collect = async (stream) => {
  const chunks = []
  for await (const chunk of stream) chunks.push(chunk)
  return Buffer.concat(chunks)
}
const sha256 = (value) => createHash('sha256').update(value).digest('hex')
const parseRecords = (state) =>
  state.recordBlocks.map((record) => ({
    collection: record.collection,
    rkey: record.rkey,
    cid: parseCid(record.cid, { flavor: 'cbor' }),
    bytes: Buffer.from(record.bytesB64, 'base64'),
  }))

await mkdir(outputDirectory, { recursive: true })
const states = {}
for (const state of source.states) {
  const commit = decode(Buffer.from(state.commitB64, 'base64'))
  const records = parseRecords(state)
  if (!RepoCommit.fromRecords(records).matches(commit)) {
    throw new Error(`reference records do not match commit for ${state.name}`)
  }
  const generate = () => collect(serializeRepo(commit, records))
  const [first, second] = await Promise.all([generate(), generate()])
  if (!first.equals(second)) {
    throw new Error(`reference serializer is byte-variable for ${state.name}`)
  }
  const { roots, blocks } = await readCarStream([first])
  const interpretedBlocks = []
  let ordinal = 0
  for await (const block of blocks) {
    interpretedBlocks.push({
      ordinal,
      cid: block.cid.toString(),
      codec: block.cid.code,
      multihashCode: block.cid.multihash.code,
      bytesB64: Buffer.from(block.bytes).toString('base64'),
    })
    ordinal += 1
  }
  const artifactName = `sa4-${state.name}.car`
  await writeFile(join(outputDirectory, artifactName), first)
  states[state.name] = {
    sourceVectorIdentifier: state.sourceVectorIdentifier,
    rev: state.rev,
    artifact: artifactName,
    byteLength: first.length,
    rawSha256: sha256(first),
    regeneration: {
      runs: 2,
      stability: 'byte-identical',
      firstSha256: sha256(first),
      secondSha256: sha256(second),
    },
    roots: roots.map((root) => root.toString()),
    blocks: interpretedBlocks,
  }
}

const transitions = []
for (const transition of source.transitions) {
  const sourceState = source.states.find((state) => state.name === transition.source)
  const targetState = source.states.find((state) => state.name === transition.target)
  if (!sourceState || !targetState) throw new Error('transition names unknown state')
  const operations = transition.operations.map((operation) => ({
    collection: operation.collection,
    rkey: operation.rkey,
    cid: operation.cid ? parseCid(operation.cid, { flavor: 'cbor' }) : null,
    prev: operation.prev ? parseCid(operation.prev, { flavor: 'cbor' }) : null,
  }))
  const replay = RepoCommit.fromState(
    Buffer.from(sourceState.lthashStateB64, 'base64'),
  ).applyOps(operations)
  const targetCommit = decode(Buffer.from(targetState.commitB64, 'base64'))
  if (!replay.matches(targetCommit)) {
    throw new Error(`reference transition replay failed for ${transition.name}`)
  }
  transitions.push({
    name: transition.name,
    source: transition.source,
    target: transition.target,
    operations: transition.operations,
    orderedOperationSha256: sha256(
      Buffer.from(JSON.stringify(transition.operations)),
    ),
    referenceReplayMatchesTarget: true,
    expectedTransitionReceiptId:
      EXPECTED_TRANSITION_RECEIPTS[transition.name] ?? null,
  })
}

const packageJson = JSON.parse(
  await readFile(join(referenceRoot, 'packages/space/package.json'), 'utf8'),
)
const driverPath = fileURLToPath(import.meta.url)
const driverSha256 = sha256(await readFile(driverPath))
const repositoryRoot = resolve(dirname(driverPath), '../../../..')
if (!driverPath.startsWith(repositoryRoot)) {
  throw new Error('generator path is outside the repository')
}

const manifest = {
  format: FORMAT,
  generator: {
    implementation: '@atproto/space.RepoCommit.applyOps+serializeRepo',
    packageVersion: packageJson.version,
    repository: 'https://github.com/bluesky-social/atproto',
    commit: head,
    nodeVersion: process.version,
    pnpmVersion: '11.11.0',
    driver: 'tests/fixtures/spaces-alpha/reference/sa4-generate.mjs',
    driverSha256,
    source: 'tests/fixtures/spaces-alpha/sa4-source.json',
    sourceSha256: sha256(sourceBytes),
    command:
      'node tests/fixtures/spaces-alpha/reference/sa4-generate.mjs ' +
      '<pinned-atproto-worktree> ' +
      'tests/fixtures/spaces-alpha/sa4-source.json ' +
      'tests/fixtures/spaces-alpha/reference ' +
      'tests/fixtures/spaces-alpha/sa4-transition.json',
  },
  localExpectation: {
    carAdapterVersion: 'sa2-car-v1',
    qualifierVersion: 'sa1-v1',
    transitionQualifierVersion: LOCAL_TRANSITION_VERSION,
  },
  states,
  transitions,
}
await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`)
