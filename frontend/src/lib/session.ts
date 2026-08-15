/**
 * Session state, through TanStack Query.
 *
 * Everything in this system is computed on read, which is precisely why a cache
 * has to invalidate properly: a stale cache after an edit displays a wrong
 * figure, and that is the failure quality attribute 2 forbids. Hand-written
 * `useEffect` fetching would mean hand-written invalidation (ADR-15).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type SessionState } from './api'

export const sessionKey = ['session'] as const

export function useSession() {
  return useQuery({
    queryKey: sessionKey,
    queryFn: () => api.get<SessionState>('/session/'),
    // The session lasts 30 days with no idle timeout, so there is nothing to
    // poll for. It is re-checked when the window regains focus, which covers
    // the case of the cookie having expired while the tab sat open.
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

export function useLogin() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (credentials: { username: string; password: string }) =>
      api.post<SessionState>('/session/', credentials),
    onSuccess: (state) => {
      queryClient.setQueryData(sessionKey, state)
    },
  })
}

export function useLogout() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => api.delete<void>('/session/'),
    onSuccess: () => {
      // Everything cached was computed for a session that no longer exists.
      queryClient.clear()
      queryClient.setQueryData(sessionKey, { authenticated: false, username: null })
    },
  })
}
