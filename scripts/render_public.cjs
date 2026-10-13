// Public association pages only: fresh anonymous browser, no stored login.
const {chromium} = require('playwright');
const dns = require('node:dns').promises;
const net = require('node:net');

async function main() {
  const url = new URL(process.argv[2]);
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error('Invalid public URL');
  const browser = await chromium.launch({headless: true});
  try {
    const context = await browser.newContext({userAgent: 'CE-Seminar-Finder/0.3 (public seminar indexing; daily)'});
    const checked = new Map();
    await context.route('**/*', async route => {
      const request = route.request();
      const target = new URL(request.url());
      if (!['https:', 'http:'].includes(target.protocol)) return route.abort();
      if (request.isNavigationRequest() && request.frame() === page.mainFrame() && target.hostname !== url.hostname) return route.abort();
      if (!checked.has(target.hostname)) {
        try {
          const ips = await dns.lookup(target.hostname, {all: true});
          checked.set(target.hostname, ips.length && ips.every(({address}) => {
            if (net.isIP(address) === 4) return !/^(?:0|10|127|169\.254|192\.168|172\.(?:1[6-9]|2\d|3[01]))\./.test(address);
            return !/^(?:::|fc|fd|fe80)/i.test(address);
          }));
        } catch { checked.set(target.hostname, false); }
      }
      if (!checked.get(target.hostname)) return route.abort();
      return route.continue();
    });
    const page = await context.newPage();
    await page.goto(url.href, {waitUntil: 'domcontentloaded', timeout: 25000});
    await page.waitForFunction(() => !document.body.innerText.includes('Loading...'), {timeout: 12000}).catch(() => {});
    await page.waitForLoadState('networkidle', {timeout: 10000}).catch(() => {});
    const text = await page.locator('body').first().innerText();
    if (text.includes('Loading...')) throw new Error('CLIENT_RENDER_INCOMPLETE');
    const html = await page.content();
    if (Buffer.byteLength(html) > 5000000) throw new Error('RENDER_TOO_LARGE');
    process.stdout.write(JSON.stringify({url: page.url(), html}));
  } finally { await browser.close(); }
}
main().catch(error => { process.stderr.write(error.message); process.exitCode = 1; });
