// Exact inline script, mocked DOM/network only: NOT a browser/accessibility test.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const html = readFileSync(new URL('../wainak_identity/templates/wainak_identity/account_deletion.html', import.meta.url), 'utf8');
const script = html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1];
const tick = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await tick(); };
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };
const signedIn = (name = 'one') => ({meta: {session_token: `fixture-${name}`, is_authenticated: true}, data: {user: {email: `${name}@example.invalid`}}});
const response = (status, body) => ({status, headers: {get: () => 'fixture-csrf'}, json: async () => body});

function environment(fetcher) {
  const elements = {}, events = {}, requests = [];
  for (const id of ['email', 'password', 'code', 'confirm', 'controls', 'status', 'verification', 'deletion',
                    'deletion-form', 'login', 'verify', 'resend', 'delete', 'logout']) {
    elements[id] = {value: '', checked: false, disabled: false, readOnly: false, hidden: ['verification', 'deletion'].includes(id),
      listeners: {}, attributes: {}, textContent: '', reportValidity: () => true,
      addEventListener(type, fn) { this.listeners[type] = fn; },
      setAttribute(key, value) { this.attributes[key] = value; }, removeAttribute(key) { delete this.attributes[key]; }};
  }
  vm.runInNewContext(script, {
    document: {getElementById: id => elements[id], querySelector: () => ({content: 'fixture-csrf'})},
    window: {addEventListener: (name, fn) => { events[name] = fn; }}, AbortController,
    setTimeout: (fn, delay) => { const timer = setTimeout(fn, delay); timer.unref(); return timer; }, clearTimeout,
    fetch: (url, options) => { requests.push({url, options}); return fetcher(url, options, requests.length); },
  });
  const login = (name = 'one') => {
    elements.email.value = `${name}@example.invalid`; elements.password.value = 'fixture-only-not-a-real-password';
    elements['deletion-form'].listeners.submit({preventDefault() {}});
  };
  return {elements, events, requests, login};
}

async function lateLogin(bodyStage) {
  const pending = deferred();
  const env = environment((url, options, index) => {
    if (index > 1) return Promise.resolve(response(401, {meta: {is_authenticated: false}}));
    return bodyStage ? Promise.resolve({status: 200, headers: {get: () => 'fixture-csrf'}, json: () => pending.promise}) : pending.promise;
  });
  env.login(); await settle(); env.events.pagehide();
  pending.resolve(bodyStage ? signedIn() : response(200, signedIn()));
  await settle();
  assert.equal(env.elements.deletion.hidden, true);
  assert.equal(env.elements.password.value, '');
  assert.equal(env.elements.email.readOnly, false);
  env.elements.logout.listeners.click(); await settle();
  assert.equal(env.requests.at(-1).options.headers['X-Session-Token'], undefined, 'Late login must not restore bearer');
}

await lateLogin(false);
await lateLogin(true);

{
  const pendingProof = deferred();
  const env = environment((url, options) => {
    if (url.endsWith('/reauthenticate')) return pendingProof.promise;
    if (url.endsWith('/auth/login')) return Promise.resolve(response(200, signedIn(JSON.parse(options.body).email.split('@')[0])));
    return Promise.resolve(response(401, {meta: {is_authenticated: false}}));
  });
  env.login('one'); await settle(); env.elements.confirm.checked = true;
  env.elements.delete.listeners.click(); await settle(); env.events.pagehide();
  env.login('two'); await settle(); pendingProof.resolve(response(200, {reauthenticated: true})); await settle();
  assert.equal(env.elements.deletion.hidden, false, 'Old request must not clear a new owned login');
  assert.equal(env.elements.confirm.checked, false, 'Deletion consent must not transfer accounts');
  assert.equal(env.requests.some(r => r.url === '/identity/v1/me'), false, 'Stale proof must not launch deletion');
  env.elements.logout.listeners.click(); await settle();
  assert.equal(env.requests.at(-1).options.headers['X-Session-Token'], 'fixture-two');
}

{
  const env = environment((url, options) => Promise.resolve(response(200, signedIn(JSON.parse(options.body).email.split('@')[0]))));
  env.login('one'); await settle(); env.elements.confirm.checked = true;
  env.login('two'); await settle();
  assert.equal(env.elements.confirm.checked, false);
  assert.equal(env.elements.email.value, 'two@example.invalid');
  env.events.pagehide();
}
console.log('PASS: 4 mocked-DOM async/consent regression scenarios; no real browser execution.');
