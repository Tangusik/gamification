/**
 * Заголовок страницы: хлебные крошки и `<h1>`, плюс `document.title` вида
 * «<Страница> — <учреждение>» (раздел 7 плана `08-web-ux-and-deploy.md`).
 *
 * Название учреждения приходит пропсом — компонент сам его нигде не
 * запрашивает и не хранит: контекст учреждения ведёт `AuthProvider`
 * (`src/auth/*`, этот файл его не трогает).
 */
import { useEffect } from 'react'
import { Link } from 'react-router'

export type Crumb = {
  label: string
  to?: string
}

type Props = {
  /** Заголовок текущей страницы — последний, некликабельный элемент цепочки. */
  title: string
  /** Промежуточные крошки, от корня к текущей странице. Последней добавляется `title`. */
  crumbs?: Crumb[]
  /** Название учреждения для заголовка вкладки; `undefined`/`null` — заголовок без него. */
  institutionName?: string | null
}

export function PageHeader({ title, crumbs = [], institutionName }: Props) {
  useEffect(() => {
    document.title =
      institutionName !== undefined && institutionName !== null && institutionName !== ''
        ? `${title} — ${institutionName}`
        : title
  }, [title, institutionName])

  return (
    <div className="page-header">
      {crumbs.length > 0 && (
        <nav aria-label="Хлебные крошки">
          <ol className="breadcrumbs">
            {crumbs.map((crumb) => (
              <li key={crumb.label}>
                {crumb.to !== undefined ? <Link to={crumb.to}>{crumb.label}</Link> : <span>{crumb.label}</span>}
              </li>
            ))}
            <li aria-current="page">{title}</li>
          </ol>
        </nav>
      )}
      <h1>{title}</h1>
    </div>
  )
}
