// Light/dark theme: default is dark (the app's identity); the user's choice is
// remembered in localStorage and stamped as data-theme on the root element,
// which the stylesheet's :root[data-theme="light"] block keys off.

const KEY = 'pk-theme'

export function getTheme() {
  try { return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark' } catch { return 'dark' }
}

export function applyTheme(theme = getTheme()) {
  document.documentElement.setAttribute('data-theme', theme)
  return theme
}

export function setTheme(theme) {
  try { localStorage.setItem(KEY, theme) } catch { /* ignore */ }
  return applyTheme(theme)
}

export function toggleTheme() {
  return setTheme(getTheme() === 'light' ? 'dark' : 'light')
}
