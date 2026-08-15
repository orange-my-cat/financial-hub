/**
 * The login screen — the only screen Stage 0 builds in full.
 *
 * One user, one password (§10.2). The password protects against another person
 * at the keyboard, not against anyone holding the machine, and the copy does
 * not pretend otherwise.
 */

import { useState, type FormEvent } from 'react'

import { ApiError } from '@/lib/api'
import { useLogin } from '@/lib/session'

export function Login() {
  const login = useLogin()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const error = login.error instanceof ApiError ? login.error : null
  const usernameError = error?.fieldError('username')
  const passwordError = error?.fieldError('password')
  const bannerMessages = error
    ? error.nonFieldMessages.length > 0
      ? error.nonFieldMessages
      : usernameError || passwordError
        ? []
        : [error.message]
    : []

  function submit(event: FormEvent) {
    event.preventDefault()
    login.mutate({ username, password })
  }

  return (
    <div className="login">
      <form className="login__card" onSubmit={submit} noValidate>
        <div className="login__mark">Financial Hub</div>

        {bannerMessages.length > 0 && (
          <div className="error-banner" role="alert">
            <span className="error-banner__label">Error</span>
            {bannerMessages.map((message) => (
              <span key={message} className="error-banner__body">
                {message}
              </span>
            ))}
          </div>
        )}

        <div className="field">
          <label className="field__label" htmlFor="username">
            Username
          </label>
          <input
            id="username"
            className={`input${usernameError ? ' input--error' : ''}`}
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          {usernameError && <span className="field__error">{usernameError}</span>}
        </div>

        <div className="field">
          <label className="field__label" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            className={`input${passwordError ? ' input--error' : ''}`}
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {passwordError && <span className="field__error">{passwordError}</span>}
        </div>

        <button
          type="submit"
          className="btn btn--primary login__submit"
          disabled={login.isPending}
        >
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
