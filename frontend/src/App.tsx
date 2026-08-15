import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { useSession } from './lib/session'
import { AccountDetail } from './screens/AccountDetail'
import { Accounts } from './screens/Accounts'
import { CashFlow } from './screens/CashFlow'
import { Dashboard } from './screens/Dashboard'
import { FxRates } from './screens/FxRates'
import { Investments } from './screens/Investments'
import { Login } from './screens/Login'
import { MonthClose } from './screens/MonthClose'
import { NetWorth } from './screens/NetWorth'
import { Settings } from './screens/Settings'
import { AppShell } from './shell/AppShell'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Every figure in this system is computed on read, so a refetch is cheap
      // and a stale figure is not. Refetching when the window regains focus is
      // the behaviour that keeps a screen honest after an edit made in another
      // tab (ADR-15).
      refetchOnWindowFocus: true,
      staleTime: 30_000,
      retry: 1,
    },
  },
})

function Routed() {
  const session = useSession()

  if (session.isPending) {
    return <div className="boot">Loading…</div>
  }

  if (!session.data?.authenticated) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }

  return (
    <Routes>
      <Route element={<AppShell />}>
        {/* Stage 5 — built last, deliberately (RISK-06). */}
        <Route index element={<Dashboard />} />
        {/* Stage 2 — the highest-value module, and the checkpoint. */}
        <Route path="net-worth" element={<NetWorth />} />
        <Route path="accounts" element={<Accounts />} />
        <Route path="accounts/:accountId" element={<AccountDetail />} />
        <Route path="month-close" element={<MonthClose />} />
        {/* Stage 3 — a parallel ledger. Nothing here touches a balance. */}
        <Route path="cash-flow" element={<CashFlow />} />
        {/* Stage 4 — FIFO by replay. No market prices, so no unrealised gain. */}
        <Route path="investments" element={<Investments />} />
        {/* Stage 1 — built first, because net worth cannot be tested without
            translation. */}
        <Route path="fx-rates" element={<FxRates />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routed />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
