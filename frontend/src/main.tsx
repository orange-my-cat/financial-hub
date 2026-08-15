import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'

import './styles/tokens.css'
import './styles/components.css'
import './styles/shell.css'
import './styles/screens.css'

const container = document.getElementById('root')
if (!container) throw new Error('No #root element in index.html')

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
