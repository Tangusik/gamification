"""Use case синхронизации профильного имени (план 11, этап 3)."""

import uuid
from dataclasses import dataclass

from app.business.ports import UnitOfWork


@dataclass(frozen=True)
class ProfileNameSyncResult:
    """Ответ синхронизации — число обновлённых членств."""

    updated: int


class SyncProfileName:
    """Обновить ``profile_name`` во всех членствах пользователя сразу.

    Обслуживает ``PATCH /internal/memberships/profile-name``: users
    сообщает об изменении имени в профиле, не зная заранее, в каких
    учреждениях состоит пользователь, поэтому читает и пишет через
    межарендный порт ``UserMemberships.set_profile_name`` — так же, как
    ``ResolveMembership`` читает через ``list_for_user`` —
    ``uow.for_institution(...)`` здесь не используется (в этом весь
    смысл отдельного пути, план 11).

    Пользователь без членств — не ошибка (``updated=0``): имя в профиле
    меняют и те, кто ни в одном учреждении не состоит.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, *, user_id: uuid.UUID, full_name: str | None
    ) -> ProfileNameSyncResult:
        async with self._uow as uow:
            updated = await uow.user_memberships.set_profile_name(user_id, full_name)
            await uow.commit()
        return ProfileNameSyncResult(updated=updated)
