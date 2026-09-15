/**
 * Ученики учреждения — `/institutions/:id/students`: список с балансом,
 * фильтром по группе и поиском по имени на клиенте. Карточка одного ученика —
 * `StudentCurrencyPage` (`/institutions/:id/students/:userId`).
 *
 * Роли: `institution_admin` — все ученики учреждения; `teacher` — ученики
 * своих групп (`GET /students?group_id=` фильтрует на сервере, здесь экран
 * отображает то, что вернул сервер, второй раз не урезает).
 *
 * UUID на экран не выводится: только имя («Без имени» — ссылка на карточку
 * для admin, чтобы задать имя) и баланс.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'

import * as groupsApi from '../api/groups'
import type { Group } from '../api/groups'
import * as studentsApi from '../api/students'
import type { StudentMember } from '../api/students'
import { useAuth } from '../auth/authContext'
import { Money } from '../components/Money'
import { PageHeader } from '../components/PageHeader'
import { ScreenState } from '../components/ScreenState'

export function StudentsPage() {
  const { id } = useParams<{ id: string }>()
  const { token, institution } = useAuth()
  const isAdmin = institution?.role === 'institution_admin'

  const [groups, setGroups] = useState<Group[] | null>(null)
  const [groupFilter, setGroupFilter] = useState('')
  const [search, setSearch] = useState('')

  const [items, setItems] = useState<StudentMember[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (token === null || id === undefined) return
    groupsApi
      .listGroups(token, id)
      .then(setGroups)
      .catch(() => undefined)
  }, [token, id])

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    studentsApi
      .listStudents(token, id, groupFilter === '' ? undefined : groupFilter)
      .then((loaded) => {
        if (!cancelled) setItems(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setLoadError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, groupFilter, attempt])

  function retry() {
    setItems(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  function groupName(groupId: string): string {
    return groups?.find((group) => group.id === groupId)?.name ?? '—'
  }

  const filtered = useMemo(() => {
    if (items === null) return null
    const query = search.trim().toLowerCase()
    if (query === '') return items
    return items.filter((member) => (member.display_name ?? '').toLowerCase().includes(query))
  }, [items, search])

  return (
    <main className="page">
      <PageHeader title="Ученики" institutionName={institution?.name} />

      <div className="field">
        <label htmlFor="student-group-filter">Группа</label>
        <select
          id="student-group-filter"
          value={groupFilter}
          onChange={(event) => setGroupFilter(event.target.value)}
        >
          <option value="">Все</option>
          {(groups ?? []).map((group) => (
            <option key={group.id} value={group.id}>
              {group.name}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="student-search">Поиск по имени</label>
        <input
          id="student-search"
          type="text"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Начните вводить имя…"
        />
      </div>

      {loadError !== null && <ScreenState state="error" error={loadError} onRetry={retry} />}
      {loadError === null && items === null && <ScreenState state="loading" />}

      {loadError === null && items !== null && items.length === 0 && isAdmin && (
        <ScreenState
          state="empty"
          message="Учеников пока нет."
          action={
            <Link className="dashboard-action" to={`/institutions/${id}/invitations`}>
              Создать ссылку-приглашение
            </Link>
          }
        />
      )}
      {loadError === null && items !== null && items.length === 0 && !isAdmin && (
        <ScreenState
          state="empty"
          message="В ваших группах нет учеников. Состав групп задаёт администратор."
        />
      )}

      {filtered !== null && filtered.length > 0 && (
        <ul className="institution-list">
          {filtered.map((member) => (
            <li key={member.user_id} className="institution-item">
              <div>
                <p className="institution-name">
                  <Link to={`/institutions/${id}/students/${member.user_id}`}>
                    {member.display_name ?? (isAdmin ? 'Задать имя' : 'Без имени')}
                  </Link>
                </p>
                <p className="institution-meta">
                  {member.group_ids.length === 0
                    ? 'без группы'
                    : member.group_ids.map((groupId) => groupName(groupId)).join(', ')}
                </p>
              </div>
              <Money amount={member.balance} />
            </li>
          ))}
        </ul>
      )}

      {filtered !== null && filtered.length === 0 && items !== null && items.length > 0 && (
        <p className="page-status">Никого не нашлось.</p>
      )}
    </main>
  )
}
