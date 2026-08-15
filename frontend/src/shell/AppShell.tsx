/**
 * The application chrome.
 *
 * One chrome — icon rail plus header — with screens swapping inside it, and the
 * ledger spine down the right edge of every one. The design board draws each
 * screen as a standalone card with the chrome repeated; that is a board
 * convention, not the application's structure.
 */

import { Outlet } from 'react-router-dom'

import { Header } from './Header'
import { Rail } from './Rail'
import { Spine } from './Spine'

export function AppShell() {
  return (
    <div className="shell">
      <Rail />
      <div className="shell__body">
        <Header />
        <main className="shell__main">
          <Outlet />
        </main>
      </div>
      <Spine />
    </div>
  )
}
