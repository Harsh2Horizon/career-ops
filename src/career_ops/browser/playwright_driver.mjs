import readline from 'node:readline';
import { createRequire } from 'node:module';
import dns from 'node:dns/promises';
import net from 'node:net';
import fs from 'node:fs';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.CAREEROPS_PLAYWRIGHT_MODULE || 'playwright');
let browser, context, page, config, step = 0;
function hostAllowed(url) {
  const u = new URL(url);
  if (config.mock) return ['127.0.0.1','localhost','[::1]'].includes(u.hostname) && ['http:','https:'].includes(u.protocol);
  return u.protocol === 'https:' && config.allowedHosts.includes(u.hostname);
}
async function safeDestination(url) {
  if (!hostAllowed(url)) throw new Error('navigation_host_not_authorized');
  if (!config.mock) {
    const addresses = await dns.lookup(new URL(url).hostname, {all:true});
    for (const {address} of addresses) {
      // Fail closed on private IPv4, IPv6 local addresses, and IPv4-mapped IPv6.
      if (net.isIP(address) === 4) {
        const n = address.split('.').map(Number);
        if (n[0] === 0 || n[0] === 10 || n[0] === 127 || n[0] >= 224 || (n[0]===169&&n[1]===254) || (n[0]===172&&n[1]>=16&&n[1]<=31) || (n[0]===192&&n[1]===168)) throw new Error('private_destination');
      } else if (address === '::1' || address.startsWith('fe80:') || /^(fc|fd|::ffff:)/i.test(address)) throw new Error('private_destination');
    }
  }
}
async function snapshot() {
  if (!hostAllowed(page.url())) throw new Error('unexpected_navigation');
  const body = (await page.locator('body').innerText()).toLowerCase();
  if (await page.locator('input[type=password],iframe[src*=recaptcha],iframe[src*=hcaptcha]').count() || /verify you are human|session expired|sign in to apply/.test(body)) throw new Error('manual_verification_required');
  return await page.evaluate(step => {
    const controls = [...document.querySelectorAll('input,textarea,select')].filter(e=>!e.disabled && e.type!=='hidden' && e.getClientRects().length);
    const fields = controls.map((e,index)=>{
      const labels = [...(e.labels || [])].map(x=>x.textContent.trim()).filter(Boolean);
      const label = (labels.join(' ') || e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.name || e.id || 'Unlabelled field').replace(/\s+/g,' ').trim();
      const field_id = `${step}:${index}:${e.name || e.id || label}`;
      e.setAttribute('data-careerops-field', field_id);
      return {field_id,label,control:e.tagName==='SELECT'?'select':(e.type || e.tagName.toLowerCase()),required:e.required||e.getAttribute('aria-required')==='true',checked:e.type==='checkbox'?e.checked:null,options:e.tagName==='SELECT'?[...e.options].map(o=>o.text.trim()):[],step};
    });
    const buttons = [...document.querySelectorAll('button,input[type=submit]')].filter(e=>!e.disabled&&e.getClientRects().length).map(e=>(e.textContent||e.value||'').trim());
    const errors = [...document.querySelectorAll('[role=alert],.error,[data-error]')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()).filter(Boolean);
    return {fields,buttons,errors,url:location.href};
  },step);
}
async function operation(request) {
  switch (request.operation) {
    case 'open': {
      config = request.config;
      await safeDestination(config.url);
      browser = await chromium.launch({headless:config.headless !== false, ...(config.executablePath?{executablePath:config.executablePath}:{})});
      context = await browser.newContext({acceptDownloads:false, serviceWorkers:'block'});
      await context.route('**/*', async route=>{
        const url = route.request().url();
        try {
          if (route.request().isNavigationRequest()) await safeDestination(url);
          else if (config.mock) { if(!hostAllowed(url)) return route.abort(); }
          else if (!hostAllowed(url) && !config.resourceHosts.includes(new URL(url).hostname)) return route.abort();
          await route.continue();
        } catch { await route.abort(); }
      });
      page = await context.newPage(); page.setDefaultTimeout(config.timeoutMs || 15000);
      const response = await page.goto(config.url,{waitUntil:'domcontentloaded'});
      if (response && response.status()>=400) throw new Error(`application_http_${response.status()}`);
      return await snapshot();
    }
    case 'snapshot': return await snapshot();
    case 'fill': {
      const target = page.locator(`[data-careerops-field=${JSON.stringify(request.field_id)}]`);
      if (await target.count() !== 1) throw new Error('ambiguous_field');
      if (request.control === 'file') {
        if (!fs.existsSync(request.value)) throw new Error('upload_file_missing');
        await target.setInputFiles(request.value);
      } else if (request.control === 'select') await target.selectOption({label:request.value});
      else if (request.control === 'checkbox') await target.setChecked(request.value === 'true');
      else if (request.control === 'radio') throw new Error('radio_group_requires_manual_adapter');
      else await target.fill(request.value);
      if (request.control === 'file') {
        const name = await target.evaluate(e=>e.files?.[0]?.name || null);
        if (name !== request.value.split(/[\\/]/).pop()) throw new Error('upload_verification_failed');
      } else if (request.control !== 'checkbox' && request.control !== 'select' && await target.inputValue() !== request.value) throw new Error('field_verification_failed');
      if (!(await target.evaluate(e=>e.checkValidity()))) throw new Error('field_validation_failed');
      return {ok:true};
    }
    case 'next': {
      if (!config.mock) throw new Error('intermediate_navigation_requires_verified_site_adapter');
      // Only explicitly nonfinal navigation controls. Never press an arbitrary submit.
      const button = page.getByRole('button',{name:/^(next|continue|review)$/i,exact:true});
      if (await button.count()!==1) throw new Error('unsupported_multistep_navigation');
      const old = JSON.stringify((await snapshot()).fields);
      await button.click();
      await page.waitForTimeout(80);
      const changed = await snapshot();
      if (JSON.stringify(changed.fields)===old || changed.errors.length) throw new Error('step_validation_failed');
      step++; return await snapshot();
    }
    case 'submit': {
      const button = page.getByRole('button',{name:/^(submit|submit application|apply|send application)$/i,exact:true});
      if (await button.count() !== 1) throw new Error('ambiguous_submit_control');
      const previous = await page.locator('body').innerText();
      const previousUrl = page.url();
      await button.click();
      await page.waitForTimeout(200);
      const text = await page.locator('body').innerText();
      const success = /application (?:has been )?(?:successfully )?(?:submitted|received)|thank you for applying/i.test(text);
      const reference = text.match(/(?:application|confirmation)\s*(?:id|reference|number)\s*[:#]\s*([\w-]+)/i)?.[1] || null;
      const receipt = page.locator('[data-application-confirmation],.application-confirmation,[role=status]').filter({visible:true});
      const receiptText = await receipt.allInnerTexts();
      const positiveReceipt = receiptText.some(t=>/application.*(?:submitted|received)|thank you for applying/i.test(t));
      const visibleForms = await page.locator('form').filter({visible:true}).count();
      const verified = success && text !== previous && (positiveReceipt || page.url() !== previousUrl || (reference && visibleForms===0));
      return {confirmed:Boolean(verified),reference,evidence:verified?(receiptText.join('\n') || text).slice(0,2000):null,url:page.url()};
    }
    case 'close': if (browser) await browser.close(); return {ok:true};
    default: throw new Error('unknown_browser_operation');
  }
}
const input = readline.createInterface({input:process.stdin,crlfDelay:Infinity});
for await (const line of input) {
  try { const result = await operation(JSON.parse(line)); process.stdout.write(JSON.stringify({result})+'\n'); }
  catch(error) { process.stdout.write(JSON.stringify({error:String(error.message).split('\n')[0]})+'\n'); }
}
if(browser) await browser.close();
