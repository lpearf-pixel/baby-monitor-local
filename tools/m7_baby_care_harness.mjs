import { createPrivateKey, createPublicKey, randomUUID } from 'node:crypto';
import readline from 'node:readline';

const root = process.env.BABY_CARE_ROOT;
const databaseUrl = process.env.TEST_DATABASE_URL;
const seedHex = process.env.M7_DEVICE_SEED_HEX;
if (!root || !databaseUrl || !seedHex || !/^[0-9a-f]{64}$/.test(seedHex)) {
  throw new Error('isolated_harness_configuration_invalid');
}
const { createDatabase } = await import(`${root}/apps/api/src/db.ts`);
const { buildApp } = await import(`${root}/apps/api/src/app.ts`);
const database = createDatabase(databaseUrl);
await database.migrate();
await database.pool.query(`truncate table
  voice_care_intent_receipts, voice_care_feeding_sessions, voice_care_leases,
  voice_care_pairing_challenges, voice_care_devices, care_event_revisions,
  measurements, care_actions, sleep_intervals, diaper_events, feeding_components,
  feeding_sessions, care_events, audit_events, sessions, babies, family_memberships,
  users, families restart identity cascade`);
const origin = 'http://127.0.0.1:8080';
const setupToken = 'm7-18-isolated-setup';
let now = new Date(process.env.M7_API_NOW || '2026-10-15T08:00:00.000Z');
const app = buildApp({
  checkDatabase: database.checkDatabase,
  database,
  appOrigin: origin,
  setupToken,
  sessionSecure: false,
  now: () => now,
  voiceCareEnabled: true,
});
const setup = await app.inject({
  method: 'POST', url: '/api/setup',
  headers: { origin, 'x-baby-care-setup-token': setupToken },
  payload: {
    familyName: 'M7 isolated family', babyDisplayName: 'synthetic-baby',
    dad: { loginName: 'dad', password: 'm7-isolated-dad' },
    mom: { loginName: 'mom', password: 'm7-isolated-mom' },
  },
});
if (setup.statusCode !== 201) throw new Error('isolated_setup_failed');
const seed = Buffer.from(seedHex, 'hex');
const pkcs8 = Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), seed]);
const privateKey = createPrivateKey({ key: pkcs8, format: 'der', type: 'pkcs8' });
const spki = privateKey.asymmetricKeyType === 'ed25519'
  ? createPublicKey(privateKey).export({ format: 'der', type: 'spki' })
  : null;
if (!spki) throw new Error('isolated_key_invalid');
const publicKey = spki.subarray(spki.length - 32);
const deviceId = randomUUID();
const leaseId = randomUUID();
const owner = await database.pool.query(`select fm.family_id, b.id baby_id, fm.user_id, fm.id membership_id
  from family_memberships fm join users u on u.id=fm.user_id and u.login_name='dad'
  join babies b on b.family_id=fm.family_id`);
const row = owner.rows[0];
if (!row) throw new Error('isolated_owner_missing');
await database.pool.query(`insert into voice_care_devices
  (id,family_id,public_key,capability,status,created_at)
  values ($1,$2,$3,'voice_care.intent.submit','active',$4)`, [deviceId, row.family_id, publicKey, now]);
await database.pool.query(`insert into voice_care_leases
  (id,family_id,baby_id,device_id,actor_user_id,actor_membership_id,client_request_id,
   issued_at,expires_at,created_at)
  values ($1,$2,$3,$4,$5,$6,$7,$8::timestamptz-interval '1 hour',$8::timestamptz+interval '7 hours',$8)`,
  [leaseId, row.family_id, row.baby_id, deviceId, row.user_id, row.membership_id, randomUUID(), now]);
await app.listen({ host: '0.0.0.0', port: Number(process.env.API_PORT || 18080) });
const address = app.server.address();
if (!address || typeof address === 'string') throw new Error('isolated_listener_missing');
console.log(JSON.stringify({ ready: true, port: address.port, deviceId, leaseId }));
const input = readline.createInterface({ input: process.stdin });
input.on('line', async (line) => {
  if (line.startsWith('set-now ')) {
    const candidate = new Date(line.slice(8).trim());
    if (!Number.isNaN(candidate.getTime())) now = candidate;
    return;
  }
  if (line.trim() === 'stop') {
    await app.close(); await database.close(); process.exit(0);
  }
});
