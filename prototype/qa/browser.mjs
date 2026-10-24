import { chromium } from 'playwright-core';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const target = process.env.WAINAK_PREVIEW_URL || pathToFileURL(path.join(root, 'dist/index.html')).href;
const output = path.join(root, 'qa/results');
await mkdir(output, { recursive: true });
const result = { target, date: new Date().toISOString(), checks: [], accessibility: [], failures: [], network: [], consoleErrors: [] };
const browser = await chromium.launch({ executablePath: process.env.WAINAK_CHROME || '/usr/bin/google-chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'ar', reducedMotion: 'reduce' });
const page = await context.newPage();
page.setDefaultTimeout(7000);
page.on('pageerror', error => result.consoleErrors.push(error.message));
page.on('request', request => {
  if (/^https?:/.test(request.url())) result.network.push(request.url());
});
const byId = id => page.getByTestId(id);

async function check(name, test) {
  try {
    await test();
    result.checks.push({ name, passed: true });
    console.log('PASS ' + name);
  } catch (error) {
    result.checks.push({ name, passed: false });
    result.failures.push({ name, message: error.message });
    console.error('FAIL ' + name + ': ' + error.message);
  }
}

async function audit(name) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const report = await page.evaluate(async () => {
    const result = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] } });
    return {
      violations: result.violations.map(v => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })) })),
      incomplete: result.incomplete.map(v => ({ id: v.id, nodes: v.nodes.length })),
      passes: result.passes.length,
    };
  });
  result.accessibility.push({ name, ...report });
  assert.equal(report.violations.length, 0, `${name}: ${JSON.stringify(report.violations)}`);
}

async function openLab() {
  const details = page.locator('details').filter({ has: byId('scenario-select') });
  if (await details.count() && !(await details.evaluate(el => el.open))) await details.locator('summary').click();
}

async function scenario(value, view) {
  await openLab();
  await byId('scenario-select').selectOption(value);
  if (view) await byId('nav-' + view).click();
}

async function fresh(route='search', profile='sara') {
  await page.goto(target);
  await byId('profile-select').selectOption(profile);
  await byId('route-' + route).click();
  await byId('terms-checkbox').check();
  await byId('start-demo').click();
}

const state = () => page.evaluate(() => window.getDemoState());

try {
  await page.goto(target);
  await byId('nav-welcome').waitFor();
  await page.evaluate(() => document.fonts.ready);
  await check('Arabic document and synthetic-data disclosure', async () => {
    assert.equal(await page.locator('html').getAttribute('lang'), 'ar');
    assert.equal(await page.locator('html').getAttribute('dir'), 'rtl');
    assert.match(await page.locator('body').innerText(), /نموذج تجريبي/);
    assert.match(await page.locator('body').innerText(), /لا حسابات أو مدفوعات حقيقية/);
  });
  await check('Welcome accessibility', () => audit('welcome-light'));
  await page.screenshot({ path: path.join(output, 'welcome-desktop.png'), fullPage: true });
  await check('Skip link is keyboard accessible', async () => {
    await page.goto(target);
    await page.keyboard.press('Tab');
    assert.match(await page.locator(':focus').innerText(), /انتقل إلى المحتوى/);
    await page.keyboard.press('Enter');
    assert.equal(await page.locator(':focus').getAttribute('id'), 'main');
  });
  await check('Request acceptance and payment do not reveal photo', async () => {
    await fresh();
    await byId('send-request').click();
    assert.equal((await state()).request, 'waiting');
    assert.equal(await byId('open-payment').count(), 0);
    await byId('accept-request').click();
    await byId('open-payment').click();
    await audit('payment-dialog');
    await byId('pay-confirm').click();
    assert.equal((await state()).opened, true);
    assert.equal((await state()).photo, 'none');
    await byId('nav-exclusive').click();
    assert.equal(await byId('request-photo').isDisabled(), true);
  });
  await check('Exclusive, core topics and photo consent are separate gates', async () => {
    await scenario('opened', 'exclusive');
    await byId('start-exclusive').click();
    await byId('confirm-exclusive').click();
    assert.equal((await state()).exclusive, 'waiting');
    assert.equal(await byId('request-photo').isDisabled(), true);
    await byId('accept-exclusive').click();
    assert.equal((await state()).photo, 'none');
    assert.equal(await byId('request-photo').isDisabled(), true);
    await byId('core-complete').click();
    await byId('request-photo').click();
    assert.equal((await state()).photo, 'waiting');
    await byId('reject-photo').click();
    assert.equal((await state()).photo, 'declined');
    assert.equal((await state()).opened, true);
    await byId('request-photo').click();
    await byId('accept-photo').click();
    assert.equal((await state()).photo, 'shared');
    assert.match(await page.locator('main').innerText(), /ليس صورة شخص حقيقي/);
    await page.screenshot({ path: path.join(output, 'exclusive-consent.png'), fullPage: true });
  });
  await check('Discovery reflects confirmed photo sharing', async () => {
    await byId('nav-discover').click();
    assert.match(await page.locator('main').innerText(), /مشاركة الصورة مؤكدة/);
    assert.doesNotMatch(await page.locator('main').innerText(), /الصورة ومعلومات الاتصال ما زالت خاصة/);
  });
  await check('Rejected request cannot open conversation or payment', async () => {
    await scenario('waiting', 'discover');
    await byId('reject-request').click();
    assert.equal(await byId('open-payment').count(), 0);
    await byId('nav-conversation').click();
    assert.equal(await byId('send-answer').count(), 0);
  });
  await check('Failed simulated payment leaves conversation closed', async () => {
    await scenario('payment-error', 'discover');
    await byId('open-payment').click();
    await byId('pay-confirm').click();
    assert.equal((await state()).opened, false);
    await audit('payment-error-dialog');
    await byId('close-payment-error').click();
  });
  await check('Subscription expiry preserves previously opened conversation', async () => {
    await scenario('accepted', 'discover');
    await byId('open-subscription').click();
    await byId('subscribe-confirm').click();
    await byId('open-included').click();
    await openLab();
    await byId('lab-subscription').click();
    assert.equal((await state()).subscription, false);
    assert.equal((await state()).opened, true);
    assert.equal((await state()).photo, 'none');
  });
  await check('Offline answers require retry; block cancels pending content', async () => {
    await scenario('offline', 'conversation');
    await byId('answer-0').check();
    assert.equal(await byId('answer-0').evaluate(el => document.activeElement === el), true);
    await byId('send-answer').click();
    assert.equal((await state()).answers['candidate:everyday'].pending, true);
    await byId('toggle-offline').click();
    assert.equal((await state()).answers['candidate:everyday'].pending, true);
    await byId('block-partner').click();
    await byId('confirm-block').click();
    assert.equal((await state()).blocked, true);
    assert.equal((await state()).answers['candidate:everyday'], undefined);
    assert.equal(await byId('retry-answer').count(), 0);
    await byId('nav-exclusive').click();
    assert.equal(await byId('request-photo').count(), 0);
  });
  await check('Separate wife spaces keep choices and answers separate', async () => {
    await scenario('married', 'married');
    await byId('space-wife-a').click();
    await byId('open-space').click();
    await byId('answer-0').check();
    await byId('send-answer').click();
    const firstAnswer = (await state()).answers['wife-a:everyday'].text;
    await byId('nav-married').click();
    await byId('space-wife-b').click();
    await byId('open-space').click();
    assert.equal((await state()).answers['wife-b:everyday'], undefined);
    assert.equal(await byId('answer-0').isChecked(), false);
    assert.equal(await page.locator('.answer-message').count(), 0);
    await byId('answer-1').check();
    await byId('send-answer').click();
    assert.equal((await state()).answers['wife-a:everyday'].text, firstAnswer);
    assert.notEqual((await state()).answers['wife-b:everyday'].text, firstAnswer);
    await byId('nav-married').click();
    await byId('space-wife-a').click();
    await byId('open-space').click();
    assert.equal(await byId('answer-0').isChecked(), true);
    assert.equal(await byId('answer-1').isChecked(), false);
  });
  await check('Four-wife limit closes dating but keeps married space', async () => {
    await scenario('four-wives', 'discover');
    assert.equal(await byId('send-request').count(), 0);
    await byId('nav-welcome').click();
    await byId('route-search').click();
    await byId('nav-discover').click();
    assert.equal(await byId('send-request').count(), 0);
    await byId('nav-married').click();
    assert.equal(await byId('open-space').isVisible(), true);
  });
  await check('Changing navigation cannot unlock dating for married woman', async () => {
    await fresh('married', 'sara');
    await byId('confirm-invite').click();
    await byId('nav-welcome').click();
    await byId('route-search').click();
    await byId('nav-discover').click();
    assert.equal(await byId('send-request').count(), 0);
    assert.match(await page.locator('main').innerText(), /التعارف غير متاح أثناء الزواج/);
  });
  await check('Engagement remains exclusive and does not increment wife count', async () => {
    await fresh('engaged', 'yaser');
    await byId('confirm-invite').click();
    assert.equal((await state()).wifeCount, 0);
    await byId('nav-welcome').click();
    await byId('route-search').click();
    await byId('nav-discover').click();
    assert.equal(await byId('send-request').count(), 0);
    assert.match(await page.locator('main').innerText(), /للمخطوبين مساحة حصرية/);
  });
  await check('Four wives cannot confirm a new engagement', async () => {
    await fresh('engaged', 'married-4');
    assert.equal(await byId('confirm-invite').count(), 0);
    assert.match(await page.locator('main').innerText(), /لا يمكن تأكيد خطبة جديدة/);
    assert.equal((await state()).wifeCount, 4);
    assert.notEqual((await state()).relationshipStatus, 'engaged');
    await byId('limit-back').click();
    await byId('route-married').click();
    await byId('start-demo').click();
    await byId('confirm-invite').click();
    assert.equal(await byId('space-wife-d').count(), 1);
  });
  await check('Fiance space preserves existing wife types, count and private answers', async () => {
    await fresh('engaged', 'married-3');
    await byId('confirm-invite').click();
    assert.equal((await state()).wifeCount, 3);
    assert.equal((await state()).activeSpace, 'fiance');
    assert.match(await page.locator('.married-hero').innerText(), /خطبة مؤكدة/);
    assert.equal(await page.locator('[data-action=space]').count(), 4);
    await byId('open-space').click();
    await byId('answer-0').check();
    await byId('send-answer').click();
    assert.ok((await state()).answers['fiance:everyday']);
    await byId('nav-married').click();
    await byId('space-wife-a').click();
    assert.match(await page.locator('.married-hero').innerText(), /ربط زوجي مؤكد/);
    await byId('open-space').click();
    assert.equal(await page.locator('.answer-message').count(), 0);
    assert.equal((await state()).answers['wife-a:everyday'], undefined);
  });
  await check('Empty declared wife list has a recoverable screen', async () => {
    await scenario('married', 'married');
    await openLab();
    await byId('wife-count').selectOption('0');
    assert.equal(await byId('open-space').count(), 0);
    assert.equal(await byId('empty-space-back').isVisible(), true);
  });
  await check('Closing modal restores keyboard focus', async () => {
    await scenario('accepted', 'discover');
    await byId('open-payment').click();
    assert.equal(await page.locator('#dialog').evaluate(el => el.contains(document.activeElement)), true);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.activeElement?.id === 'open-payment');
    assert.equal(await page.locator('#dialog').evaluate(el => el.open), false);
  });
  for (const [state, view] of [['new', 'discover'], ['opened', 'conversation'], ['exclusive', 'exclusive'], ['married', 'married']]) {
    await check(view + ' accessibility', async () => {
      await scenario(state, view);
      await audit(view + '-light');
    });
  }
  await check('Dark mode accessibility', async () => {
    await byId('theme-toggle').click();
    await audit('married-dark');
    await page.screenshot({ path: path.join(output, 'married-dark.png'), fullPage: true });
    await byId('theme-toggle').click();
  });
  await check('Mobile reflow across five views', async () => {
    await page.setViewportSize({ width: 320, height: 860 });
    for (const view of ['welcome', 'discover', 'conversation', 'exclusive', 'married']) {
      await byId('nav-' + view).click();
      const dims = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
      assert.ok(dims.scroll <= dims.client + 1, `${view} horizontal overflow: ${JSON.stringify(dims)}`);
    }
    await page.screenshot({ path: path.join(output, 'married-mobile.png'), fullPage: true });
    await audit('married-mobile');
  });
  await check('Text enlargement retains layout and controls', async () => {
    await page.setViewportSize({ width: 390, height: 900 });
    await page.addStyleTag({ content: 'html { font-size: 200% !important; } body { font-size: 36px !important; }' });
    for (const view of ['welcome', 'married']) {
      await byId('nav-' + view).click();
      const dims = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
      assert.ok(dims.scroll <= dims.client + 1, `${view} enlarged text overflow: ${JSON.stringify(dims)}`);
    }
    await page.screenshot({ path: path.join(output, 'married-large-text.png'), fullPage: true });
  });
  await check('Reload clears synthetic session state', async () => {
    await page.reload();
    assert.equal((await state()).registered, false);
    assert.deepEqual((await state()).answers, {});
  });
  await check('No external requests or page exceptions', async () => {
    assert.deepEqual(result.network, []);
    assert.deepEqual(result.consoleErrors, []);
  });
} catch (error) {
  result.failures.push({ name: 'test setup or traversal', message: error.stack });
} finally {
  await writeFile(path.join(output, 'browser-results.json'), JSON.stringify(result, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ checks: result.checks.length, failures: result.failures.length, accessibilityViews: result.accessibility.length }));
if (result.failures.length) process.exitCode = 1;
