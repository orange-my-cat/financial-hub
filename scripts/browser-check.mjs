/**
 * Automated browser check.
 *
 * Loads the application in a real Chromium, signs in, walks the routes, and
 * reports every console error, page error and failed request — plus a
 * screenshot of each screen.
 *
 * This exists because Stage 1 shipped a blank FX screen. Every backend test
 * passed and the bundle typechecked and built; the defect was an API envelope
 * mismatch that only a browser could see. "The tests pass" and "the screen
 * renders" are different claims, and until now only one of them was ever
 * checked.
 *
 * Run it through `scripts/browser-check.ps1`, which starts the throwaway Vite
 * instance it needs. See that file for why the check server is separate.
 *
 *   BASE_URL   default http://host.docker.internal:5174
 *   OUT_DIR    default /work/screenshots
 *   USERNAME / PASSWORD   credentials to sign in with
 */

import { mkdir } from 'node:fs/promises'
import process from 'node:process'

import { chromium } from 'playwright'

const BASE = process.env.BASE_URL ?? 'http://host.docker.internal:5174'
const OUT = process.env.OUT_DIR ?? '/work/screenshots'
const USERNAME = process.env.USERNAME ?? 'ivan'
const PASSWORD = process.env.PASSWORD ?? ''

/** Noise that is not a defect. Keep this list short and justified. */
const IGNORED = [
  /Download the React DevTools/i,
  /\[vite\] connect(ing|ed)/i,
]

const ROUTES = [
  { path: '/', name: 'dashboard' },
  { path: '/net-worth', name: 'net-worth' },
  { path: '/accounts', name: 'accounts' },
  { path: '/month-close', name: 'month-close' },
  { path: '/cash-flow', name: 'cash-flow' },
  { path: '/investments', name: 'investments' },
  { path: '/fx-rates', name: 'fx-rates' },
  { path: '/settings', name: 'settings' },
]

const problems = []

function record(route, kind, message) {
  if (IGNORED.some((pattern) => pattern.test(message))) return
  problems.push({ route, kind, message })
}

async function main() {
  await mkdir(OUT, { recursive: true })

  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })

  let route = 'startup'
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      record(route, message.type(), message.text())
    }
  })
  page.on('pageerror', (error) => record(route, 'pageerror', error.message))
  page.on('requestfailed', (request) =>
    record(route, 'requestfailed', `${request.url()} — ${request.failure()?.errorText}`),
  )

  // -- sign in ------------------------------------------------------------
  route = 'login'
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}/00-login.png` })

  if (await page.locator('#username').count()) {
    await page.fill('#username', USERNAME)
    await page.fill('#password', PASSWORD)
    await page.click('button[type=submit]')
    await page.waitForTimeout(1800)
  }

  if (await page.locator('#username').count()) {
    problems.push({ route: 'login', kind: 'fatal', message: 'still on the login screen' })
  }

  // -- walk every route ---------------------------------------------------
  for (const target of ROUTES) {
    route = target.path
    await page.goto(`${BASE}${target.path}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1200)

    // A blank screen is the failure this whole script exists to catch.
    const rendered = await page.evaluate(() => {
      const root = document.getElementById('root')
      return (root?.innerText ?? '').trim().length
    })
    if (rendered < 20) {
      problems.push({
        route: target.path,
        kind: 'blank',
        message: `#root rendered ${rendered} characters of text`,
      })
    }

    // The shell scrolls in an inner container, so `fullPage` alone captures
    // only the first viewport. Released for the capture and nowhere else — this
    // style is injected after the render being checked, never before it.
    await page.addStyleTag({
      content: `.shell { height: auto !important; }
                .shell__main { overflow: visible !important; }
                .spine { overflow: visible !important; }`,
    })
    await page.waitForTimeout(200)
    await page.screenshot({ path: `${OUT}/${target.name}.png`, fullPage: true })
  }

  await browser.close()

  // -- report -------------------------------------------------------------
  if (problems.length === 0) {
    console.log(`OK — ${ROUTES.length} routes rendered with no console or network errors.`)
    return
  }

  console.log(`${problems.length} problem(s):\n`)
  for (const problem of problems) {
    console.log(`[${problem.kind}] ${problem.route}\n    ${problem.message}\n`)
  }
  process.exitCode = 1
}

main().catch((error) => {
  console.error(`browser-check failed to run: ${error.message}`)
  process.exitCode = 2
})
