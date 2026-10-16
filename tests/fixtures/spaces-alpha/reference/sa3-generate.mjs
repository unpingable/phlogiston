#!/usr/bin/env node

import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const PINNED_COMMIT = '89deb9faca20e56fa2a262fe9746ed52bc1095ba'
const FORMAT = 'spaces-alpha-sa3-reference-vector-v1'
const SOURCE_VECTOR = 'sa1:valid-initial:89deb9f'
const LOCAL_ADAPTER_VERSION = 'sa2-car-v1'
const LOCAL_INTEROP_VERSION = 'sa3-v1'
const EXPECTED_RECEIPT =
  'sha256:c7584ad43983317c1a251aef0b9ee4801669579898a84ca3528c18e8e868abf0'

const [referenceArgument, inputArgument, carOutputArgument] = process.argv.slice(2)
if (!referenceArgument || !inputArgument) {
  throw new Error(
    'usage: sa3-generate.mjs <pinned-atproto-worktree> <sa1-vector-json>',
  )
}

const referenceRoot = resolve(referenceArgument)
const inputPath = resolve(inputArgument)
const head = execFileSync('git', ['-C', referenceRoot, 'rev-parse', 'HEAD'], {
  encoding: 'utf8',
}).trim()
if (head !== PINNED_COMMIT) {
  throw new Error(`reference worktree is ${head}, expected ${PINNED_COMMIT}`)
}

const loadReferenceModule = (relative) =>
  import(pathToFileURL(join(referenceRoot, relative)).href)
const [{ readCarStream }, { decode }, { parseCid }, { serializeRepo }] =
  await Promise.all([
    loadReferenceModule('packages/common/dist/index.js'),
    loadReferenceModule('packages/lex/lex-cbor/dist/index.js'),
    loadReferenceModule('packages/lex/lex-data/dist/index.js'),
    loadReferenceModule('packages/space/dist/index.js'),
  ])

const fixture = JSON.parse(await readFile(inputPath, 'utf8'))
const vector = fixture.valid.initial
if (vector.sourceVectorIdentifier !== SOURCE_VECTOR) {
  throw new Error('SA1 input source vector does not match the pinned SA3 input')
}

const commitBytes = Buffer.from(vector.commitB64, 'base64')
const commit = decode(commitBytes)
const records = vector.recordBlocks.map((record) => ({
  collection: record.collection,
  rkey: record.rkey,
  cid: parseCid(record.cid, { flavor: 'cbor' }),
  bytes: Buffer.from(record.bytesB64, 'base64'),
}))

const collect = async (stream) => {
  const chunks = []
  for await (const chunk of stream) chunks.push(chunk)
  return Buffer.concat(chunks)
}
const generate = () => collect(serializeRepo(commit, records))
const [first, second] = await Promise.all([generate(), generate()])
const firstSha256 = createHash('sha256').update(first).digest('hex')
const secondSha256 = createHash('sha256').update(second).digest('hex')
if (!first.equals(second)) {
  throw new Error('reference serializer output was not byte-identical')
}

const { roots, blocks } = await readCarStream([first])
const referenceBlocks = []
let ordinal = 0
for await (const block of blocks) {
  referenceBlocks.push({
    ordinal,
    cid: block.cid.toString(),
    codec: block.cid.code,
    multihashCode: block.cid.multihash.code,
    bytesB64: Buffer.from(block.bytes).toString('base64'),
  })
  ordinal += 1
}

const packageJson = JSON.parse(
  await readFile(join(referenceRoot, 'packages/space/package.json'), 'utf8'),
)
const driverPath = fileURLToPath(import.meta.url)
const driverSha256 = createHash('sha256')
  .update(await readFile(driverPath))
  .digest('hex')
const repositoryRoot = resolve(dirname(driverPath), '../../../..')
if (carOutputArgument) await writeFile(resolve(carOutputArgument), first)

const manifest = {
  format: FORMAT,
  artifact: {
    carB64: first.toString('base64'),
    byteLength: first.length,
    rawSha256: firstSha256,
  },
  generator: {
    implementation: '@atproto/space.serializeRepo',
    packageVersion: packageJson.version,
    repository: 'https://github.com/bluesky-social/atproto',
    commit: head,
    nodeVersion: process.version,
    pnpmVersion: '11.11.0',
    driver: 'tests/fixtures/spaces-alpha/reference/sa3-generate.mjs',
    driverSha256,
    command:
      'node tests/fixtures/spaces-alpha/reference/sa3-generate.mjs ' +
      '<pinned-atproto-worktree> ' +
      'tests/fixtures/spaces-alpha/sa1-qualification.json ' +
      'tests/fixtures/spaces-alpha/reference/sa3-golden.car',
  },
  regeneration: {
    runs: 2,
    stability: 'byte-identical',
    firstSha256,
    secondSha256,
  },
  referenceInterpretation: {
    roots: roots.map((root) => root.toString()),
    blocks: referenceBlocks,
  },
  localExpectation: {
    adapterVersion: LOCAL_ADAPTER_VERSION,
    interoperabilityVersion: LOCAL_INTEROP_VERSION,
    sourceVectorIdentifier: SOURCE_VECTOR,
    sa1QualificationReceiptIds: [EXPECTED_RECEIPT],
  },
}

// Avoid accidentally making the generator depend on its invocation directory.
if (!driverPath.startsWith(repositoryRoot)) {
  throw new Error('generator path is outside the repository')
}
process.stdout.write(`${JSON.stringify(manifest, null, 2)}\n`)
