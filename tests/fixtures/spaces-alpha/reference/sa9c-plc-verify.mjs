#!/usr/bin/env node

import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const PINNED_COMMIT = '2ed82a5ccf1b424aa5e2f6c5b461dc0ee133278b'
const [referenceArgument, fixtureArgument] = process.argv.slice(2)
if (!referenceArgument || !fixtureArgument) {
  throw new Error(
    'usage: sa9c-plc-verify.mjs <pinned-did-method-plc-worktree> <fixture-json>',
  )
}

const referenceRoot = resolve(referenceArgument)
const fixturePath = resolve(fixtureArgument)
const head = execFileSync('git', ['-C', referenceRoot, 'rev-parse', 'HEAD'], {
  encoding: 'utf8',
}).trim()
if (head !== PINNED_COMMIT) {
  throw new Error(`reference worktree is ${head}, expected ${PINNED_COMMIT}`)
}

const load = (relative) => import(pathToFileURL(join(referenceRoot, relative)).href)
const requireFromReference = createRequire(join(referenceRoot, 'package.json'))
const cborPath = requireFromReference.resolve('@ipld/dag-cbor')
const cidPath = requireFromReference.resolve('multiformats/cid')
const [{ CID }, cbor, common, plc] = await Promise.all([
  import(pathToFileURL(cidPath).href),
  import(pathToFileURL(cborPath).href),
  load('node_modules/@atproto/common/dist/index.js'),
  load('packages/lib/dist/index.js'),
])

const fixtureBytes = await readFile(fixturePath)
const fixture = JSON.parse(fixtureBytes)
if (fixture.generator.commit !== PINNED_COMMIT) {
  throw new Error('fixture generator commit does not match the reference pin')
}

for (const [name, history] of Object.entries(fixture.histories)) {
  const supplied = history.entries.map((entry, ordinal) => {
    const bytes = Buffer.from(entry.operationDagCborBase64, 'base64')
    const operation = cbor.decode(bytes)
    if (!Buffer.from(cbor.encode(operation)).equals(bytes)) {
      throw new Error(`${name}: operation ${ordinal} is not canonical DAG-CBOR`)
    }
    return {
      ...entry,
      ordinal,
      bytes,
      operation,
      cid: CID.parse(entry.cid),
      createdAt: new Date(entry.createdAt),
    }
  })
  const ordered = [...supplied].sort((a, b) => a.createdAt - b.createdAt)
  let active = []
  const nullified = new Set()
  for (const item of ordered) {
    const computedCid = await common.cidForCbor(item.operation)
    if (!computedCid.equals(item.cid)) throw new Error(`${name}: CID mismatch`)
    if (active.length === 0) {
      await plc.assureValidCreationOp(history.did, item.operation)
    } else {
      const decision = await plc.assureValidNextOp(
        history.did,
        active,
        item.operation,
        item.createdAt,
      )
      for (const cid of decision.nullified) nullified.add(cid.toString())
      active = active.filter((prior) => !decision.nullified.some((cid) => cid.equals(prior.cid)))
    }
    active.push({ cid: item.cid, operation: item.operation, createdAt: item.createdAt })
  }
  const marked = new Set(supplied.filter((item) => item.nullified).map((item) => item.cid.toString()))
  if ([...marked].sort().join('\n') !== [...nullified].sort().join('\n')) {
    throw new Error(`${name}: nullification flags disagree with reference rules`)
  }
  const final = active.at(-1).operation
  const data = plc.opToData(history.did, final)
  const document = data === null ? null : plc.formatDidDoc(data)
  if (JSON.stringify(document) !== JSON.stringify(history.expectedDocument)) {
    throw new Error(`${name}: derived document differs from fixture expectation`)
  }
}

process.stdout.write(
  JSON.stringify({
    fixtureSha256: createHash('sha256').update(fixtureBytes).digest('hex'),
    referenceCommit: head,
    historiesVerified: Object.keys(fixture.histories),
  }) + '\n',
)
