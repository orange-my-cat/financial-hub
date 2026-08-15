import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { useSession } from './lib/session'
import { Login } from './screens/Login'
import { Placeholder, SCREENS } from './screens/Placeholder'
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
        <Route index element={<Placeholder {...SCREENS.dashboard!} />} />
        <Route path="net-worth" element={<Placeholder {...SCREENS.netWorth!} />} />
        <Route path="accounts" element={<Placeholder {...SCREENS.accounts!} />} />
        <Route path="accounts/:accountId" element={<Placeholder {...SCREENS.accounts!} />} />
        <Route path="month-close" element={<Placeholder {...SCREENS.monthClose!} />} />
        <Route path="cash-flow" element={<Placeholder {...SCREENS.cashFlow!} />} />
        <Route path="investments" element={<Placeholder {...SCREENS.investments!} />} />
        <Route path="fx-rates" element={<Placeholder {...SCREENS.fxRates!} />} />
        <Route path="settings" element={<Placeholder {...SCREENS.settings!} />} />
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
