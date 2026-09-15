import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Шрифты — npm-пакеты `@fontsource/*`, версия фиксируется в
// `package-lock.json` (В11/а, `.claude/plans/08-web-ux-and-deploy.md`).
// Подключены только начертания и подсеты, которые реально используются в
// `index.css`: Inter 400/600/700 (обычный текст, заголовки/подписи, `<strong>`)
// в latin и cyrillic — интерфейс двуязычный (термины/коды об ошибках —
// латиница, тексты — кириллица). Press Start 2P — один вес 400, тоже оба
// подсета: кириллица в шрифте есть (Google Fonts, проверено по метаданным
// пакета), фолбэк на monospace в `--font-pixel` остаётся на случай сбоя
// загрузки.
import '@fontsource/inter/latin-400.css'
import '@fontsource/inter/latin-600.css'
import '@fontsource/inter/latin-700.css'
import '@fontsource/inter/cyrillic-400.css'
import '@fontsource/inter/cyrillic-600.css'
import '@fontsource/inter/cyrillic-700.css'
import '@fontsource/press-start-2p/latin-400.css'
import '@fontsource/press-start-2p/cyrillic-400.css'

import { AppRouter } from './router'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppRouter />
  </StrictMode>,
)
