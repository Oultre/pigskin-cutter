import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { applyTheme } from './theme.js'
import './styles.css'

applyTheme()   // set the saved light/dark theme before first paint (no flash)

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
