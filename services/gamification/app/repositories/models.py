"""SQLAlchemy-модели сервиса gamification.

Модели — деталь реализации хранилища; домен (``app.business.domain``)
про них не знает. Соответствие полей проверяется явным мэппингом в
``app/repositories/sql_alchemy.py``, а не статическими протоколами, как
в users: сущности здесь — конкретные dataclass'ы, а не Protocol.

Перечисления хранятся строками (``native_enum=False``) — добавление
значения не должно требовать ``ALTER TYPE`` в проде (раздел 7). UUID —
через ``sqlalchemy.Uuid``: отдельный ``GUID`` из
``fastapi-users-db-sqlalchemy`` этому сервису не нужен, зависимости от
библиотеки здесь нет вовсе.

``memberships.user_id`` — без внешнего ключа: пользователи живут в
другой базе (I1), ссылочную целостность через границу баз обеспечить
нечем — это записанный риск (см. план, раздел 1).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.repositories.database import Base

# Длина колонок под значения перечислений — с запасом к самому длинному
# ("institution_admin"), чтобы новое значение не требовало миграции типа.
ENUM_LENGTH = 32

# Длина колонки токена приглашения — с запасом к ``secrets.token_urlsafe(32)``
# (обычно 43 символа), см. ``app.business.domain.entities.create_invitation``.
TOKEN_LENGTH = 64

# Имя участника в пределах учреждения (В4/D1) и имя группы (В5/G2) — обе
# ограничены 100 символами по решению плана.
DISPLAY_NAME_LENGTH = 100
GROUP_NAME_LENGTH = 100

# Длина колонки типа операции с валютой — с запасом к самому длинному
# значению ``TransactionKind`` (план 06).
TRANSACTION_KIND_LENGTH = 32

# Комментарий к начислению необязателен, до 200 символов (В2/C2).
CURRENCY_COMMENT_LENGTH = 200

# Позиция каталога маркета (план 07, У6): название 1..100, описание
# ≤ 500 или NULL.
PRIVILEGE_TITLE_LENGTH = 100
PRIVILEGE_DESCRIPTION_LENGTH = 500

# Статус покупки — строкой, тот же приём, что и у TransactionKind (У8
# плана 06): новое значение не требует ALTER TYPE.
PURCHASE_STATUS_LENGTH = 16


def _values_callable(enum_class: type) -> list[str]:
    """Отдать SQLAlchemy значения перечисления, а не имена членов."""
    return [member.value for member in enum_class]


def _utcnow() -> datetime:
    """Текущий момент в UTC, осознанный по часовому поясу."""
    return datetime.now(UTC)


class InstitutionModel(Base):
    """Учреждение — арендатор системы."""

    __tablename__ = "institutions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(length=255), nullable=False)
    kind: Mapped[InstitutionKind] = mapped_column(
        Enum(
            InstitutionKind,
            native_enum=False,
            length=ENUM_LENGTH,
            values_callable=_values_callable,
        ),
        default=InstitutionKind.SCHOOL,
        nullable=False,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class InvitationModel(Base):
    """Приглашение в учреждение — бессрочное, отзыв только вручную (F1).

    Токен хранится открыто в колонке ``token`` (F5, решение владельца
    против рекомендации — см. базу знаний): нужно для перепечатки QR.
    """

    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(length=TOKEN_LENGTH), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            native_enum=False,
            length=ENUM_LENGTH,
            values_callable=_values_callable,
        ),
        default=UserRole.STUDENT,
        nullable=False,
    )
    max_uses: Mapped[int] = mapped_column(nullable=False)
    uses_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    # NULL — не отозвано (F1: срока жизни нет, отзыв только вручную).
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("token"),
        Index("ix_invitations_institution_id", "institution_id"),
    )


class MembershipModel(Base):
    """Членство пользователя в учреждении — носитель роли и статуса.

    ``ON DELETE CASCADE`` только на ``institution_id``: удаление
    учреждения не должно оставлять сирот. Каскада на пользователя нет —
    он живёт в другой базе (записанный риск, раздел 1).
    """

    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            native_enum=False,
            length=ENUM_LENGTH,
            values_callable=_values_callable,
        ),
        default=UserRole.STUDENT,
        nullable=False,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(
            MembershipStatus,
            native_enum=False,
            length=ENUM_LENGTH,
            values_callable=_values_callable,
        ),
        default=MembershipStatus.ACTIVE,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    # Приглашение, по которому пришёл участник; NULL — заведено иначе
    # (например, создатель учреждения). Удаление приглашения не должно
    # удалять членство — только терять на него ссылку.
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("invitations.id", ondelete="SET NULL"), nullable=True
    )
    # Имя участника в пределах учреждения (В4/D1). NULL, пока админ его
    # не заполнил — у пришедших по приглашению оно изначально пустое.
    display_name: Mapped[str | None] = mapped_column(
        String(length=DISPLAY_NAME_LENGTH), nullable=True
    )

    __table_args__ = (
        # Пара уникальна: второе членство сделало бы выбор роли
        # неоднозначным.
        UniqueConstraint("user_id", "institution_id"),
        Index("ix_memberships_user_id", "user_id"),
    )


class GroupModel(Base):
    """Группа учеников в учреждении (кружок, параллель — В5/G2).

    Имя уникально в пределах учреждения без учёта регистра — держит
    функциональный уникальный индекс по ``lower(name)``, а не проверка в
    коде: тот же принцип, что и уникальность членства (раздел 7).
    """

    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(length=GROUP_NAME_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        Index(
            "uq_groups_institution_id_lower_name",
            "institution_id",
            text("lower(name)"),
            unique=True,
        ),
    )


class GroupStudentModel(Base):
    """Прикрепление ученика к группе — многие-ко-многим (В5/G2: несколько
    групп у одного ученика, поэтому ``UNIQUE(membership_id)`` нет).
    """

    __tablename__ = "group_students"

    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="CASCADE"), primary_key=True
    )


class GroupTeacherModel(Base):
    """Прикрепление преподавателя к группе — многие-ко-многим."""

    __tablename__ = "group_teachers"

    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="CASCADE"), primary_key=True
    )


class CurrencyTransactionModel(Base):
    """История операций с валютой — неизменяема по построению (У4).

    Неизменяемость держат два слоя: у ``CurrencyRepository`` нет методов
    изменения и удаления, а миграция ``0003`` ставит на таблицу триггер
    ``BEFORE UPDATE OR DELETE``, который бросает исключение — этот
    класс сам по себе от него не защищает, проверяется db-тестом.

    ``membership_id``/``created_by_membership_id`` — ``ON DELETE
    RESTRICT``: удаление участника не должно осиротить его финансовую
    историю или сделать автора начисления неопределённым (риск 3 плана).
    ``reverses_id`` уникален (В3/E2) — сторнировать запись можно только
    один раз, гонку двух параллельных сторно решает это же ограничение.
    """

    __tablename__ = "currency_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        String(length=TRANSACTION_KIND_LENGTH), nullable=False
    )
    amount: Mapped[int] = mapped_column(nullable=False)
    comment: Mapped[str | None] = mapped_column(
        String(length=CURRENCY_COMMENT_LENGTH), nullable=True
    )
    created_by_membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="RESTRICT"), nullable=False
    )
    operation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("currency_transactions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        # Пространство operation_id общее для начислений и сторно (В4/I1).
        UniqueConstraint("institution_id", "operation_id"),
        # Одну операцию можно сторнировать только один раз (В3/E2).
        UniqueConstraint("reverses_id"),
        CheckConstraint("amount <> 0", name="amount_not_zero"),
        # История ученика читается новыми сверху (У1) — функциональный
        # индекс с явным порядком, тот же приём, что и у групп.
        Index(
            "ix_currency_transactions_membership_id_created_at",
            "membership_id",
            text("created_at DESC"),
        ),
    )


class CurrencyBalanceModel(Base):
    """Баланс ученика — отдельная таблица (У2), не ``SUM`` по истории.

    Обновляется упсертом (``INSERT … ON CONFLICT (membership_id) DO
    UPDATE``) в той же транзакции, что и вставка записи истории —
    решение нужно будущему атомарному списанию (``UPDATE … WHERE
    balance >= :cost``, вопрос 4 плана, вне этого этапа).
    """

    __tablename__ = "currency_balances"

    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="RESTRICT"), primary_key=True
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        # П3 плана 07: баланс никогда не уходит в минус, ноль допустим.
        # Второй рубеж поверх атомарного условного UPDATE в
        # SqlAlchemyCurrencyRepository.record и SqlAlchemyMarketRepository.purchase —
        # SQLSTATE 23514 переводится в InsufficientBalanceError.
        CheckConstraint("balance >= 0", name="balance_non_negative"),
    )


class PrivilegeModel(Base):
    """Позиция каталога маркета (план 07, Ч1) — управляет только admin (П2).

    Удаления нет (У3), есть ``is_active``. ``stock=NULL`` — без
    ограничения (В5/L2), списывается атомарно условным ``UPDATE`` в
    ``SqlAlchemyMarketRepository.purchase``.
    """

    __tablename__ = "privileges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(length=PRIVILEGE_TITLE_LENGTH), nullable=False
    )
    description: Mapped[str | None] = mapped_column(
        String(length=PRIVILEGE_DESCRIPTION_LENGTH), nullable=True
    )
    price: Mapped[int] = mapped_column(nullable=False)
    stock: Mapped[int | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("stock IS NULL OR stock >= 0", name="stock_non_negative"),
        Index("ix_privileges_institution_id", "institution_id"),
    )


class PurchaseModel(Base):
    """Покупка привилегии (план 07, В2/M2) — ``title``/``price`` сняты на
    момент покупки (У4), смена цены позиции задним числом её не меняет.

    ``debit_transaction_id``/``refund_transaction_id`` ссылаются на
    ``currency_transactions`` (``kind=purchase``/``purchase_refund``) —
    ``ON DELETE RESTRICT``, история неизменяема (У4 плана 06).
    """

    __tablename__ = "purchases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="RESTRICT"), nullable=False
    )
    privilege_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("privileges.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(length=PRIVILEGE_TITLE_LENGTH), nullable=False
    )
    price: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(length=PURCHASE_STATUS_LENGTH), nullable=False
    )
    operation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    debit_transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("currency_transactions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    refund_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("currency_transactions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memberships.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        # Пространство operation_id общее с currency_transactions в
        # пределах учреждения (план 07: «запись покупки получает тот же
        # operation_id, что сама покупка») — это ограничение защищает
        # саму таблицу purchases отдельно.
        UniqueConstraint("institution_id", "operation_id"),
        UniqueConstraint("debit_transaction_id"),
        UniqueConstraint("refund_transaction_id"),
        Index(
            "ix_purchases_institution_id_status_created_at",
            "institution_id",
            "status",
            "created_at",
        ),
    )
