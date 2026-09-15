/// Карточка ученика (teacher, admin) — перенос
/// `services/web/src/pages/StudentCurrencyPage.tsx`: имя и статус, группы
/// (правка — только admin), баланс с историей операций, форма начисления
/// (teacher и admin), сторно (только admin, только для `manual_accrual` без
/// сторно) и покупки ученика (только admin — `teacher` не отправляет
/// `GET .../purchases?user_id=` вовсе).
///
/// Имя, статус и группы ученика — из уже загруженного [studentsListProvider]
/// (общего со `StudentsScreen`): отдельного ресурса «один ученик» в
/// контракте нет, тот же приём, что у веба.
///
/// **Политика `operation_id`** — в [pendingAccrualsProvider] и
/// [pendingReversalsProvider] (`pending_operations.dart`): id заводится при
/// первой попытке и остаётся тем же при любом отказе, кроме успеха,
/// `OPERATION_ID_CONFLICT` и (для сторно) `TRANSACTION_ALREADY_REVERSED`.
///
/// Пока попытка начисления не закрыта, [PendingAccrualAttempt] хранит ещё и
/// отправленное тело (`amount`/`comment`) — форма показывает ровно его и
/// блокирует поля, в том числе после пересборки экрана: это не даёт повтору
/// уйти с другим телом при том же id (находка ревью безопасности, medium).
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/auth_api.dart' show MembershipStatus, UserRole;
import '../../api/errors.dart';
import '../../api/groups_api.dart';
import '../../api/market_admin_api.dart' show Purchase;
import '../../api/staff_currency_api.dart';
import '../../api/students_api.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../i18n/labels.dart';
import '../../router/paths.dart';
import '../../ui/confirm_dialog.dart';
import '../../ui/design_tokens.dart';
import '../../ui/money.dart';
import '../../ui/saved_notice.dart';
import '../../ui/screen_state.dart';
import '../student/formatting.dart';
import 'pending_operations.dart';
import 'student_card_providers.dart';
import 'students_providers.dart';

/// Экран «Ученик» для ролей `teacher` и `institution_admin`. Подключается
/// роутером напрямую с `userId` из пути.
class StudentCardScreen extends ConsumerStatefulWidget {
  const StudentCardScreen({super.key, required this.userId});

  final String userId;

  @override
  ConsumerState<StudentCardScreen> createState() => _StudentCardScreenState();
}

class _StudentCardScreenState extends ConsumerState<StudentCardScreen> {
  final _accrueFormKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _amountController = TextEditingController();
  final _commentController = TextEditingController();
  bool _nameInitialized = false;

  bool _savingName = false;
  Object? _nameError;

  bool _savingStatus = false;
  Object? _statusError;

  String _addGroupId = '';
  bool _groupBusy = false;
  Object? _groupError;

  bool _accruing = false;
  Object? _accrueError;

  /// `operationId` попытки, чьё тело сейчас отражено в полях формы —
  /// не даёт [_syncAccrualFields] переписывать поля на каждой пересборке
  /// (что стёрло бы правку, которую пользователь ещё не отправил) и
  /// отличает «поля уже синхронизированы» от «синхронизации не было».
  String? _syncedAccrualOperationId;

  String? _reversingTransactionId;
  Object? _reverseError;

  @override
  void dispose() {
    _nameController.dispose();
    _amountController.dispose();
    _commentController.dispose();
    super.dispose();
  }

  Future<void> _handleSaveName(InstitutionContext institution) async {
    final trimmed = _nameController.text.trim();
    if (trimmed.isEmpty) return;
    setState(() {
      _savingName = true;
      _nameError = null;
    });
    final client = ref.read(apiClientProvider);
    try {
      await updateStudent(client, institution.id, widget.userId, UpdateMemberInput(displayName: trimmed));
      if (!mounted) return;
      setState(() => _savingName = false);
      ref.invalidate(studentsListProvider);
      showSavedNotice(context);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _savingName = false;
        _nameError = error;
      });
    }
  }

  Future<void> _applyStatus(MembershipStatus status, InstitutionContext institution) async {
    setState(() {
      _savingStatus = true;
      _statusError = null;
    });
    final client = ref.read(apiClientProvider);
    try {
      await updateStudent(client, institution.id, widget.userId, UpdateMemberInput(status: status));
      if (!mounted) return;
      setState(() => _savingStatus = false);
      ref.invalidate(studentsListProvider);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _savingStatus = false;
        _statusError = error;
      });
    }
  }

  Future<void> _handleStatusChange(MembershipStatus status, InstitutionContext institution) async {
    if (status == MembershipStatus.suspended) {
      final confirmed = await showConfirmDialog(
        context,
        title: 'Приостановить ученика?',
        description: 'Доступ пропадёт сразу.',
        confirmLabel: 'Приостановить',
        danger: true,
      );
      if (confirmed != true || !mounted) return;
    }
    await _applyStatus(status, institution);
  }

  Future<void> _handleAddGroup(InstitutionContext institution) async {
    if (_addGroupId.isEmpty) return;
    setState(() {
      _groupBusy = true;
      _groupError = null;
    });
    final client = ref.read(apiClientProvider);
    try {
      await addStudentToGroup(client, institution.id, _addGroupId, widget.userId);
      if (!mounted) return;
      setState(() {
        _groupBusy = false;
        _addGroupId = '';
      });
      ref.invalidate(studentsListProvider);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _groupBusy = false;
        _groupError = error;
      });
    }
  }

  // Убрать из группы — без подтверждения (раздел 7 плана `08-web-ux-and-deploy.md`, обратимо).
  Future<void> _handleRemoveGroup(String groupId, InstitutionContext institution) async {
    setState(() {
      _groupBusy = true;
      _groupError = null;
    });
    final client = ref.read(apiClientProvider);
    try {
      await removeStudentFromGroup(client, institution.id, groupId, widget.userId);
      if (!mounted) return;
      setState(() => _groupBusy = false);
      ref.invalidate(studentsListProvider);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _groupBusy = false;
        _groupError = error;
      });
    }
  }

  /// Заполнить поля формы телом незавершённой попытки [pending], если оно
  /// ещё не отражено в них. Вызывается из `build` — тот же приём, что
  /// инициализация `_nameController` из данных ученика (см. `_nameInitialized`
  /// ниже): меняет только контроллеры, без `setState`.
  void _syncAccrualFields(PendingAccrualAttempt? pending) {
    if (pending == null) {
      _syncedAccrualOperationId = null;
      return;
    }
    if (_syncedAccrualOperationId == pending.operationId) return;
    _syncedAccrualOperationId = pending.operationId;
    _amountController.text = pending.amount.toString();
    _commentController.text = pending.comment ?? '';
  }

  Future<void> _handleAccrue(InstitutionContext institution) async {
    final userId = ref.read(sessionProvider).user!.id;
    final key = PendingAccrualKey(userId: userId, institutionId: institution.id, studentUserId: widget.userId);
    final pending = ref.read(pendingAccrualsProvider.notifier);
    final existingAttempt = ref.read(pendingAccrualsProvider)[key];

    final PendingAccrualAttempt attempt;
    if (existingAttempt != null) {
      // Попытка уже отправлена и не закрыта — поля заблокированы и
      // показывают ровно это тело (`_syncAccrualFields`), повторяем его
      // без повторной валидации формы.
      attempt = existingAttempt;
    } else {
      if (!(_accrueFormKey.currentState?.validate() ?? false)) return;
      final comment = _commentController.text.trim();
      attempt = pending.start(
        key,
        amount: int.parse(_amountController.text.trim()),
        comment: comment.isEmpty ? null : comment,
      );
    }

    setState(() {
      _accruing = true;
      _accrueError = null;
    });
    final client = ref.read(apiClientProvider);
    try {
      await accrue(
        client,
        institution.id,
        widget.userId,
        AccrueInput(operationId: attempt.operationId, amount: attempt.amount, comment: attempt.comment),
      );
      pending.clear(key);
      if (!mounted) return;
      _amountController.clear();
      _commentController.clear();
      _syncedAccrualOperationId = null;
      setState(() => _accruing = false);
      ref.invalidate(studentCurrencyHistoryProvider(widget.userId));
      ref.invalidate(studentsListProvider);
      showSavedNotice(context);
    } catch (error) {
      // Сброс id — только на однозначном исходе (Ч5, `pending_operations.dart`):
      // `OPERATION_ID_CONFLICT` значит, что id уже занят другой операцией,
      // повтор с ним никогда не пройдёт. Кода «сумма изменилась» у начисления
      // нет, поэтому больше сбрасывать не на что.
      final code = error is ApiError ? error.code : null;
      if (code == 'OPERATION_ID_CONFLICT') {
        pending.clear(key);
        _syncedAccrualOperationId = null;
        ref.invalidate(studentCurrencyHistoryProvider(widget.userId));
      }
      if (!mounted) return;
      setState(() {
        _accruing = false;
        _accrueError = error;
      });
    }
  }

  /// Текст ошибки начисления. `OPERATION_ID_CONFLICT` у общего
  /// `messageForError` — обобщённый; здесь код однозначно означает, что
  /// именно эта попытка с этим id уже прошла с другими данными, поэтому
  /// текст конкретнее, чем в `lib/i18n/error_messages.dart` (тот не
  /// меняется — сообщение локальное для этого экрана).
  String _accrueErrorMessage(Object error) {
    if (error is ApiError && error.code == 'OPERATION_ID_CONFLICT') {
      return 'Начисление с этим id уже прошло с другими данными. Проверьте историю операций.';
    }
    return messageForError(error);
  }

  Future<void> _handleReverseTap(
    CurrencyTransaction transaction,
    InstitutionContext institution,
    String studentName,
  ) async {
    setState(() => _reverseError = null);
    final confirmed = await showConfirmDialog(
      context,
      title: 'Сторнировать начисление?',
      description: '${transaction.amount} — $studentName',
      confirmLabel: 'Сторнировать',
      danger: true,
    );
    if (confirmed != true || !mounted) return;
    await _performReverse(transaction, institution);
  }

  Future<void> _performReverse(CurrencyTransaction transaction, InstitutionContext institution) async {
    final userId = ref.read(sessionProvider).user!.id;
    final key = PendingReversalKey(userId: userId, institutionId: institution.id, transactionId: transaction.id);
    final pending = ref.read(pendingReversalsProvider.notifier);
    final operationId = pending.take(key);

    setState(() => _reversingTransactionId = transaction.id);
    final client = ref.read(apiClientProvider);
    try {
      await reverse(client, institution.id, transaction.id, operationId);
      pending.clear(key);
      if (!mounted) return;
      setState(() => _reversingTransactionId = null);
      ref.invalidate(studentCurrencyHistoryProvider(widget.userId));
      showSavedNotice(context);
    } catch (error) {
      final code = error is ApiError ? error.code : null;
      if (code == 'OPERATION_ID_CONFLICT' || code == 'TRANSACTION_ALREADY_REVERSED') {
        pending.clear(key);
        ref.invalidate(studentCurrencyHistoryProvider(widget.userId));
      }
      if (!mounted) return;
      setState(() {
        _reversingTransactionId = null;
        _reverseError = error;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final institution = ref.watch(sessionProvider.select((state) => state.institution));
    final isAdmin = institution?.role == UserRole.institutionAdmin;
    final currencyName = institution?.currencyName;
    final studentsAsync = ref.watch(studentsListProvider);
    final groupsAsync = isAdmin ? ref.watch(staffGroupsProvider) : null;
    final historyAsync = ref.watch(studentCurrencyHistoryProvider(widget.userId));
    // Ключевое ограничение роли (Ч5): teacher не должен слать этот запрос
    // вовсе — провайдер даже не читается (`ref.watch`), если не admin.
    final purchasesAsync = isAdmin ? ref.watch(studentPurchasesProvider(widget.userId)) : null;

    final currentStudent =
        studentsAsync.value != null ? findStudent(studentsAsync.value!, widget.userId) : null;

    if (institution == null) {
      // Роутер не даёт открыть карточку без выбранного учреждения — здесь
      // просто safety net на случай гонки с выходом/сменой учреждения.
      return const Scaffold(body: ScreenStateLoading());
    }

    final staffUserId = ref.watch(sessionProvider.select((state) => state.user!.id));
    final accrualKey = PendingAccrualKey(
      userId: staffUserId,
      institutionId: institution.id,
      studentUserId: widget.userId,
    );
    final pendingAccrual = ref.watch(pendingAccrualsProvider.select((state) => state[accrualKey]));
    _syncAccrualFields(pendingAccrual);

    return Scaffold(
      appBar: AppBar(
        title: Text(currentStudent?.displayName ?? 'Ученик', style: Theme.of(context).textTheme.titleMedium),
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            await Future.wait([
              ref.refresh(studentsListProvider.future),
              ref.refresh(studentCurrencyHistoryProvider(widget.userId).future),
              if (isAdmin) ref.refresh(studentPurchasesProvider(widget.userId).future),
            ]);
          } catch (_) {
            // Ошибка каждой секции показывается на месте ниже.
          }
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            studentsAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) => ScreenStateError(
                message: messageForError(error),
                code: error is ApiError ? error.code : null,
                onRetry: () => ref.invalidate(studentsListProvider),
              ),
              data: (students) {
                final student = findStudent(students, widget.userId);
                if (student == null) {
                  return const Padding(
                    padding: EdgeInsets.symmetric(vertical: AppSpacing.lg),
                    child: Text('Ученик не найден.', style: TextStyle(color: AppColors.textMuted)),
                  );
                }
                if (!_nameInitialized) {
                  _nameController.text = student.displayName ?? '';
                  _nameInitialized = true;
                }
                final studentName = student.displayName ?? 'Без имени';
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _buildNameSection(student, institution, isAdmin),
                    _buildStatusSection(student, institution, isAdmin),
                    _buildGroupsSection(student, groupsAsync?.value, institution, isAdmin),
                    _buildAccrualForm(institution, currencyName, pendingAccrual),
                    _buildHistorySection(historyAsync, isAdmin, currencyName, studentName, institution),
                    if (isAdmin) ...[
                      const SizedBox(height: AppSpacing.lg),
                      _buildPurchasesSection(purchasesAsync!),
                    ],
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildNameSection(StudentMember student, InstitutionContext institution, bool isAdmin) {
    if (!isAdmin) {
      return Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.md),
        child: Text(student.displayName ?? 'Без имени', style: Theme.of(context).textTheme.titleMedium),
      );
    }
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _nameController,
              maxLength: 100,
              decoration: const InputDecoration(labelText: 'Имя', hintText: 'Без имени'),
              enabled: !_savingName,
            ),
            if (_nameError != null)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Text(messageForError(_nameError!), style: const TextStyle(color: AppColors.danger)),
              ),
            Align(
              alignment: Alignment.centerRight,
              child: OutlinedButton(
                onPressed: _savingName ? null : () => _handleSaveName(institution),
                child: Text(_savingName ? 'Сохраняем…' : 'Сохранить имя'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStatusSection(StudentMember student, InstitutionContext institution, bool isAdmin) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text('Статус: '),
              if (isAdmin)
                DropdownButton<MembershipStatus>(
                  value: student.status == MembershipStatus.invited ? null : student.status,
                  hint: Text(statusLabels[student.status] ?? ''),
                  items: [MembershipStatus.active, MembershipStatus.suspended]
                      .map((status) => DropdownMenuItem(value: status, child: Text(statusLabels[status] ?? '')))
                      .toList(),
                  onChanged: _savingStatus
                      ? null
                      : (value) {
                          if (value != null) unawaited(_handleStatusChange(value, institution));
                        },
                )
              else
                Text(statusLabels[student.status] ?? ''),
            ],
          ),
          if (_statusError != null)
            Text(messageForError(_statusError!), style: const TextStyle(color: AppColors.danger)),
        ],
      ),
    );
  }

  Widget _buildGroupsSection(
    StudentMember student,
    List<Group>? groups,
    InstitutionContext institution,
    bool isAdmin,
  ) {
    final availableGroups =
        isAdmin ? (groups ?? const <Group>[]).where((group) => !student.groupIds.contains(group.id)).toList() : const <Group>[];

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Группы', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: AppSpacing.sm),
          if (student.groupIds.isEmpty)
            const Text('без группы', style: TextStyle(color: AppColors.textMuted))
          else
            for (final groupId in student.groupIds)
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(groupNameOrDash(groups, groupId)),
                trailing: isAdmin
                    ? TextButton(
                        onPressed: _groupBusy ? null : () => _handleRemoveGroup(groupId, institution),
                        child: const Text('Убрать'),
                      )
                    : null,
              ),
          if (isAdmin && groups != null && availableGroups.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: [
                Expanded(
                  child: DropdownButtonFormField<String>(
                    initialValue: _addGroupId.isEmpty ? null : _addGroupId,
                    decoration: const InputDecoration(labelText: 'Добавить в группу'),
                    items: [
                      for (final group in availableGroups) DropdownMenuItem(value: group.id, child: Text(group.name)),
                    ],
                    onChanged: _groupBusy ? null : (value) => setState(() => _addGroupId = value ?? ''),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                OutlinedButton(
                  onPressed: _addGroupId.isEmpty || _groupBusy ? null : () => _handleAddGroup(institution),
                  child: const Text('Добавить'),
                ),
              ],
            ),
          ],
          if (_groupError != null)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.xs),
              child: Text(messageForError(_groupError!), style: const TextStyle(color: AppColors.danger)),
            ),
        ],
      ),
    );
  }

  Widget _buildAccrualForm(
    InstitutionContext institution,
    String? currencyName,
    PendingAccrualAttempt? pendingAccrual,
  ) {
    final locked = _accruing || pendingAccrual != null;
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Form(
          key: _accrueFormKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Начислить${currencyName != null ? ' $currencyName' : ''}',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: AppSpacing.sm),
              if (pendingAccrual != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: Text(
                    'Предыдущее начисление ${pendingAccrual.amount} не подтверждено — повторите отправку',
                    style: const TextStyle(color: AppColors.textMuted),
                  ),
                ),
              TextFormField(
                controller: _amountController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Сумма'),
                enabled: !locked,
                validator: (value) {
                  final amount = int.tryParse((value ?? '').trim());
                  if (amount == null || amount < 1 || amount > 10000) {
                    return 'Введите число от 1 до 10000';
                  }
                  return null;
                },
              ),
              const SizedBox(height: AppSpacing.sm),
              TextFormField(
                controller: _commentController,
                maxLength: 200,
                decoration: const InputDecoration(labelText: 'Комментарий (необязательно)'),
                enabled: !locked,
              ),
              if (_accrueError != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: Text(_accrueErrorMessage(_accrueError!), style: const TextStyle(color: AppColors.danger)),
                ),
              Align(
                alignment: Alignment.centerRight,
                child: OutlinedButton(
                  onPressed: _accruing ? null : () => _handleAccrue(institution),
                  child: Text(_accruing ? 'Начисляем…' : 'Начислить'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHistorySection(
    AsyncValue<CurrencyAccount> historyAsync,
    bool isAdmin,
    String? currencyName,
    String studentName,
    InstitutionContext institution,
  ) {
    return historyAsync.when(
      loading: () => const ScreenStateLoading(),
      error: (error, _) => ScreenStateError(
        message: messageForError(error),
        code: error is ApiError ? error.code : null,
        onRetry: () => ref.invalidate(studentCurrencyHistoryProvider(widget.userId)),
      ),
      data: (account) {
        final reversedIds = <String>{
          for (final transaction in account.transactions)
            if (transaction.kind == TransactionKind.reversal && transaction.reversesId != null)
              transaction.reversesId!,
        };
        bool canReverse(CurrencyTransaction transaction) =>
            isAdmin && transaction.kind == TransactionKind.manualAccrual && !reversedIds.contains(transaction.id);

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Text('Баланс: '),
                Money(amount: account.balance, size: 20),
                if (currencyName != null) ...[const SizedBox(width: AppSpacing.xs), Text(currencyName)],
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            if (_reverseError != null)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Text(messageForError(_reverseError!), style: const TextStyle(color: AppColors.danger)),
              ),
            if (account.transactions.isEmpty)
              const ScreenStateEmpty(message: 'Операций пока нет.')
            else
              Card(
                child: Column(
                  children: [
                    for (final transaction in account.transactions)
                      ListTile(
                        title: Text(transactionKindLabels[transaction.kind] ?? ''),
                        subtitle: Text(
                          '${transaction.createdByName ?? roleLabels[transaction.createdByRole] ?? ''} · '
                          '${formatDateTime(transaction.createdAt)}'
                          '${transaction.comment != null && transaction.comment!.isNotEmpty ? ' · ${transaction.comment}' : ''}',
                        ),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Money(amount: transaction.amount, showPlus: true),
                            if (canReverse(transaction)) ...[
                              const SizedBox(width: AppSpacing.sm),
                              TextButton(
                                onPressed: _reversingTransactionId != null
                                    ? null
                                    : () => _handleReverseTap(transaction, institution, studentName),
                                child: Text(_reversingTransactionId == transaction.id ? 'Сторнируем…' : 'Сторно'),
                              ),
                            ],
                          ],
                        ),
                      ),
                  ],
                ),
              ),
          ],
        );
      },
    );
  }

  Widget _buildPurchasesSection(AsyncValue<List<Purchase>> purchasesAsync) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Покупки', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: AppSpacing.sm),
        purchasesAsync.when(
          loading: () => const ScreenStateLoading(),
          error: (error, _) => ScreenStateError(
            message: messageForError(error),
            code: error is ApiError ? error.code : null,
            onRetry: () => ref.invalidate(studentPurchasesProvider(widget.userId)),
          ),
          data: (purchases) {
            if (purchases.isEmpty) {
              return const ScreenStateEmpty(message: 'Покупок пока нет.');
            }
            return Card(
              child: Column(
                children: [
                  for (final purchase in purchases)
                    ListTile(
                      title: Text(purchase.title),
                      subtitle: Text(
                        '${purchaseStatusLabels[purchase.status] ?? ''} · ${formatDateTime(purchase.createdAt)}',
                      ),
                      trailing: Money(amount: -purchase.price),
                    ),
                ],
              ),
            );
          },
        ),
        const SizedBox(height: AppSpacing.sm),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            onPressed: () => context.go(marketPurchasesPath),
            child: const Text('Все заявки учреждения'),
          ),
        ),
      ],
    );
  }
}
