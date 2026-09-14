"""Сущности бизнес-слоя: учреждения и членства.

Слой не зависит ни от чего, кроме stdlib — ни FastAPI, ни SQLAlchemy,
ни pydantic здесь быть не должно (проверяется тестом импортов). Роль
пользователя живёт не на пользователе, а на членстве: один аккаунт
может состоять сразу в нескольких учреждениях с разными ролями.
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.business.domain.access_errors import InvitationInvalidError
from app.business.domain.enums import (
    InstitutionKind,
    MembershipStatus,
    PurchaseStatus,
    TransactionKind,
    UserRole,
)

# Длина случайной части токена приглашения в байтах (256 бит, Р3/F1).
INVITATION_TOKEN_BYTES = 32


@dataclass
class Institution:
    """Учреждение — арендатор системы."""

    id: uuid.UUID
    name: str
    kind: InstitutionKind
    created_by: uuid.UUID
    created_at: datetime


@dataclass
class Membership:
    """Членство пользователя в учреждении — носитель роли и статуса."""

    id: uuid.UUID
    user_id: uuid.UUID
    institution_id: uuid.UUID
    role: UserRole
    status: MembershipStatus
    created_at: datetime
    # Приглашение, по которому пришёл участник (F3–F7); ``None`` — членство
    # заведено иначе (например, создатель учреждения).
    invitation_id: uuid.UUID | None = None
    # Имя участника в пределах учреждения (В4/D1). ``None``, пока админ
    # его не заполнил — у пришедших по приглашению оно изначально пустое.
    display_name: str | None = None

    def is_active(self) -> bool:
        """Даёт ли это членство доступ к учреждению прямо сейчас."""
        return self.status is MembershipStatus.ACTIVE


@dataclass
class Invitation:
    """Приглашение в учреждение — бессрочное, с ограничением числа применений.

    Срока жизни нет (F1: отзыв только вручную). Токен хранится
    восстановимо (F5, решение владельца против рекомендации) — колонка
    ``token`` в хранилище открытая, хеш не заводится.
    """

    id: uuid.UUID
    institution_id: uuid.UUID
    token: str
    role: UserRole
    max_uses: int
    uses_count: int
    created_by: uuid.UUID
    created_at: datetime
    revoked_at: datetime | None

    def is_revoked(self) -> bool:
        """Отозвано ли приглашение вручную (F1)."""
        return self.revoked_at is not None

    def is_exhausted(self) -> bool:
        """Исчерпан ли лимит применений (F2)."""
        return self.uses_count >= self.max_uses

    def accept(self, *, user_id: uuid.UUID, now: datetime) -> Membership:
        """Принять приглашение: новое членство плюс собственный счётчик.

        Вызывается только после проверки существующего членства
        пользователя (F7) — эта проверка находится вне сущности, ей
        нужен доступ к хранилищу. Здесь проверяется только собственная
        валидность приглашения (раздел 5, шаг 3).

        :raises InvitationInvalidError: приглашение отозвано или лимит
            применений исчерпан.
        """
        if self.is_revoked() or self.is_exhausted():
            raise InvitationInvalidError
        self.uses_count += 1
        return Membership(
            id=uuid.uuid4(),
            user_id=user_id,
            institution_id=self.institution_id,
            role=self.role,
            status=MembershipStatus.ACTIVE,
            created_at=now,
            invitation_id=self.id,
        )


def create_invitation(
    *, institution_id: uuid.UUID, created_by: uuid.UUID, max_uses: int, now: datetime
) -> Invitation:
    """Завести бессрочное приглашение (F1) с ограничением применений (F2).

    Роль в этом этапе всегда ``student`` (F3): приглашения преподавателей
    и админов не входят в объём.
    """
    return Invitation(
        id=uuid.uuid4(),
        institution_id=institution_id,
        token=secrets.token_urlsafe(INVITATION_TOKEN_BYTES),
        role=UserRole.STUDENT,
        max_uses=max_uses,
        uses_count=0,
        created_by=created_by,
        created_at=now,
        revoked_at=None,
    )


@dataclass
class Group:
    """Группа учеников и преподавателей в учреждении (В5/G2, против
    рекомендации G1): у ученика может быть несколько групп, связь
    «ученик ↔ группа» — многие-ко-многим без ограничения на одну пару.
    """

    id: uuid.UUID
    institution_id: uuid.UUID
    name: str
    created_at: datetime


@dataclass(frozen=True)
class NewInstitution:
    """Результат создания учреждения вместе с членством его создателя."""

    institution: Institution
    admin_membership: Membership


def create_institution(
    *, name: str, kind: InstitutionKind, created_by: uuid.UUID, now: datetime
) -> NewInstitution:
    """Завести учреждение и членство создателя одним актом (E1).

    Учреждение без администратора никому не принадлежит, поэтому это не
    два независимых шага, а одна операция домена: обе сущности рождаются
    вместе, с уже решёнными идентификаторами и временем создания.
    Хранилище лишь фиксирует то, что здесь уже решено, — вставка обеих
    записей идёт в одной транзакции Unit of Work (``use_cases.institutions``).
    """
    institution = Institution(
        id=uuid.uuid4(),
        name=name,
        kind=kind,
        created_by=created_by,
        created_at=now,
    )
    admin_membership = Membership(
        id=uuid.uuid4(),
        user_id=created_by,
        institution_id=institution.id,
        role=UserRole.INSTITUTION_ADMIN,
        status=MembershipStatus.ACTIVE,
        created_at=now,
    )
    return NewInstitution(institution=institution, admin_membership=admin_membership)


@dataclass
class CurrencyTransaction:
    """Запись истории операций с валютой — неизменяема (У4).

    Неизменяемость держат два слоя: у порта ``CurrencyRepository`` нет
    методов изменения и удаления, а миграция ставит на таблицу триггер
    ``BEFORE UPDATE OR DELETE``. У сторно (``kind=REVERSAL``) ``amount``
    отрицателен, ``reverses_id`` указывает на исходную запись (В3/E2).
    """

    id: uuid.UUID
    institution_id: uuid.UUID
    membership_id: uuid.UUID
    kind: TransactionKind
    amount: int
    comment: str | None
    created_by_membership_id: uuid.UUID
    operation_id: uuid.UUID
    reverses_id: uuid.UUID | None
    created_at: datetime


@dataclass
class Privilege:
    """Позиция каталога маркета (план 07, Ч1) — управляет только admin (П2).

    ``stock=None`` — без ограничения (В5/L2): списывается атомарно через
    ``UPDATE … WHERE stock IS NULL OR stock > 0``, самого поля это не
    трогает.
    """

    id: uuid.UUID
    institution_id: uuid.UUID
    title: str
    description: str | None
    price: int
    stock: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class Purchase:
    """Покупка привилегии (план 07, В2/M2) — снимок ``title``/``price`` на
    момент покупки (У4), смена цены позиции задним числом её не меняет.

    ``debit_transaction_id`` — запись списания (``kind=purchase``),
    ``refund_transaction_id`` — запись возврата при отказе
    (``kind=purchase_refund``), ``None`` пока покупка не отклонена.
    """

    id: uuid.UUID
    institution_id: uuid.UUID
    membership_id: uuid.UUID
    privilege_id: uuid.UUID
    title: str
    price: int
    status: PurchaseStatus
    operation_id: uuid.UUID
    debit_transaction_id: uuid.UUID
    refund_transaction_id: uuid.UUID | None
    created_at: datetime
    resolved_at: datetime | None
    resolved_by_membership_id: uuid.UUID | None
