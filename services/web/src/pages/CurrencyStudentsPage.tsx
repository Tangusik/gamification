/**
 * Ученики с балансами — `/institutions/:id/currency`. Доступно `teacher`
 * (только ученики своих групп) и `institution_admin` (всё учреждение);
 * видимость решает бэкенд по контракту `GET /students`, экран отображает то,
 * что вернул сервер.
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'

import * as groupsApi from '../api/groups'
import type { Group } from '../api/groups'
import * as studentsApi from '../api/students'
import type { StudentMember } from '../api/students'
import { useAuth } from '../auth/authContext'
import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'

export function CurrencyStudentsPage() {
  const { id } = useParams<{ id: string }>()
  const { token, institution } = useAuth()

  const [groups, setGroups] = useState<Group[] | null>(null)
  const [groupFilter, setGroupFilter] = useState('')

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

  return (
    <>
      <main className="page">
        <h1>Начисления</h1>

        {institution?.role === 'institution_admin' && (
          <p>
            <Link to={`/institutions/${id}/students`}>Управление учениками</Link>
          </p>
        )}

        <div className="field">
          <label htmlFor="currency-group-filter">Группа</label>
          <select
            id="currency-group-filter"
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

        {loadError !== null && (
          <>
            <FormError message={messageForError(loadError)} />
            <button type="button" onClick={retry}>
              Повторить
            </button>
          </>
        )}

        {loadError === null && items === null && (
          <p className="page-status" role="status">
            Загрузка…
          </p>
        )}

        {items !== null && items.length === 0 && <p>Учеников пока нет.</p>}

        {items !== null && items.length > 0 && (
          <ul className="institution-list">
            {items.map((member) => (
              <li key={member.user_id} className="institution-item">
                <div>
                  <p className="institution-name">
                    <Link to={`/institutions/${id}/currency/${member.user_id}`}>
                      {member.display_name ?? member.user_id}
                    </Link>
                  </p>
                  <p className="institution-meta">Баланс: {member.balance}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  )
}
