/**
 * Fixture generator for the SA9e local reference-PDS witness.
 *
 * Copy this file into `packages/pds/tests/space/` in the exact pinned ATProto
 * checkout before invoking the command documented in SPACES-ALPHA-SA9E.md.
 * It intentionally writes only the CAR and public verification context. The
 * transient delegation token, Space credential, and private keys never leave
 * the reference test process.
 */
import { createHash } from 'node:crypto'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { TestNetworkNoAppView } from '@atproto/dev-env'
import { verifyRepoCarFull } from '@atproto/space'
import {
  type Actor,
  SpaceClient,
  TEST_COLLECTION,
  TEST_COLLECTION_ALT,
} from '../_space.js'

describe('SA9e local reference export', () => {
  let network: TestNetworkNoAppView
  let sc: SpaceClient
  let alice: Actor
  let bob: Actor

  beforeAll(async () => {
    network = await TestNetworkNoAppView.create({
      dbPostgresSchema: 'space_sa9e_export',
      extraPdses: 1,
    })
    sc = new SpaceClient(network)
    alice = await sc.createActor('sa9e-alice', network.pds)
    bob = await sc.createActor('sa9e-bob', network.extraPdses[0], 'test2')
  })

  afterAll(async () => {
    await network?.close()
  })

  it('exports a credentialed getRepo CAR and public qualification context', async () => {
    const outputDir = process.env.SA9E_OUTPUT_DIR
    if (!outputDir) throw new Error('SA9E_OUTPUT_DIR is required')

    const space = await sc.createSpace(alice, {
      skey: 'sa9e-local-read-only',
      members: [bob],
    })
    const records = [
      {
        collection: TEST_COLLECTION,
        rkey: 'first',
        text: 'SA9e synthetic first record',
        createdAt: '2026-08-21T18:00:00.000Z',
      },
      {
        collection: TEST_COLLECTION_ALT,
        rkey: 'second',
        text: 'SA9e synthetic second record',
        createdAt: '2026-08-21T18:00:01.000Z',
      },
    ]
    for (const item of records) {
      await sc.write(bob, space, {
        collection: item.collection,
        rkey: item.rkey,
        record: {
          $type: item.collection,
          text: item.text,
          createdAt: item.createdAt,
        },
      })
    }

    const credential = await sc.credentialFor(bob, space)
    const requestUrl = new URL('/xrpc/com.atproto.space.getRepo', bob.pds.url)
    requestUrl.searchParams.set('space', space)
    requestUrl.searchParams.set('repo', bob.did)
    const response = await credential.fetch(requestUrl)
    expect(response.status).toBe(200)
    expect(response.headers.get('content-type')).toContain(
      'application/vnd.ipld.car',
    )
    const car = new Uint8Array(await response.arrayBuffer())

    const keypair = await bob.pds.ctx.actorStore.keypair(bob.did)
    const didKey = keypair.did()
    const recovered = await verifyRepoCarFull([car], {
      space,
      author: bob.did,
      didKey,
    })
    expect(recovered.records).toHaveLength(records.length)
    expect(recovered.repo.matches(recovered.commit)).toBe(true)

    const state = await sc.repoState(bob, space)
    await mkdir(outputDir, { recursive: true })
    await writeFile(join(outputDir, 'sa9e-local-pds.car'), car)
    await writeFile(
      join(outputDir, 'sa9e-local-pds.json'),
      JSON.stringify(
        {
          format: 'spaces-alpha-sa9e-local-pds-v1',
          upstream: {
            repository: 'bluesky-social/atproto',
            commit: '89deb9faca20e56fa2a262fe9746ed52bc1095ba',
            package: '@atproto/space',
            packageVersion: '0.0.1',
          },
          acquisition: {
            method: 'GET',
            endpoint: 'com.atproto.space.getRepo',
            requestedUrl: requestUrl.toString(),
            status: response.status,
            contentType: response.headers.get('content-type'),
            bodyLength: car.byteLength,
            bodySha256: createHash('sha256').update(car).digest('hex'),
            transport: 'reference-local-http-pds',
            authenticated: true,
            credentialsPersisted: false,
          },
          space,
          authorityDid: alice.did,
          authorDid: bob.did,
          authorDidKey: didKey,
          authorPublicKeyB64: Buffer.from(keypair.publicKeyBytes()).toString(
            'base64',
          ),
          signatureAlgorithm: 'ES256K',
          repoState: {
            rev: state?.rev,
            setHashB64: state
              ? Buffer.from(state.setHash).toString('base64')
              : null,
            recordCount: recovered.records.length,
            records: recovered.records.map((record) => ({
              collection: record.collection,
              rkey: record.rkey,
              cid: record.cid.toString(),
            })),
          },
          claims: {
            referenceCarVerified: true,
            governanceAuthority: false,
            completeHistory: false,
            currentForever: false,
          },
        },
        null,
        2,
      ) + '\n',
    )
  })
})
