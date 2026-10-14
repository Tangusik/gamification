"""Общие фейки use case'ов бизнес-слоя (план 11, этап 2).

``CreateInstitution`` и ``AcceptInvitation`` с этого этапа зависят от
``UserAccounts`` (нужен только ``get_full_name`` — профильное имя для
``profile_name``). Большинству тестов этого пакета профильное имя не
важно, поэтому фейк по умолчанию ничего не знает и не мешает: один
класс на весь пакет вместо копии в каждом файле.
"""

import uuid

from app.business.domain.errors import UsersUnavailableError


class NullUserAccounts:
    """Фейк ``UserAccounts``, не владеющий профильными именами.

    ``get_full_name`` по умолчанию отвечает ``None`` — как если бы
    профиль пока не заполнен. ``unavailable=True`` имитирует
    недоступность users (план 11, п. 6: это не повод отказать в
    создании учреждения/принятии приглашения — только
    ``profile_name=None``).
    """

    def __init__(
        self,
        *,
        full_names: dict[uuid.UUID, str | None] | None = None,
        unavailable: bool = False,
    ) -> None:
        self._full_names = full_names or {}
        self._unavailable = unavailable
        self.full_name_calls: list[uuid.UUID] = []

    async def create_account(
        self, *, email: str, password: str, full_name: str | None = None
    ) -> uuid.UUID:
        raise NotImplementedError(
            "NullUserAccounts не предназначен для create_account — "
            "CreateInstitution и AcceptInvitation его не вызывают"
        )

    async def get_full_name(self, user_id: uuid.UUID) -> str | None:
        self.full_name_calls.append(user_id)
        if self._unavailable:
            raise UsersUnavailableError
        return self._full_names.get(user_id)
