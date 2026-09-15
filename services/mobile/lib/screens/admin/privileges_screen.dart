/// Каталог привилегий (admin) — перенос `services/web/src/pages/PrivilegesPage.tsx`.
///
/// Список включает и скрытые позиции (`is_active: false`) — они отмечены
/// подписью «Скрыта». Правка каждой позиции — своя карточка с формой (В отличие
/// от веба, где редактируются только цена/остаток/активность, здесь доступны
/// также название и описание — `UpdatePrivilegeInput` их поддерживает, а
/// задание явно просит именно такой состав). Отправляются только изменившиеся
/// поля (У11): `description`/`stock` — через сентинел [unsetField], пустая
/// строка остатка — явный `null` («без ограничения», L2).
///
/// Скрыть/показать позицию — часть той же формы правки, без отдельного
/// подтверждения (раздел 7 плана `08-web-ux-and-deploy.md`: действие
/// обратимое).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errors.dart';
import '../../api/market_admin_api.dart';
import '../../api/market_api.dart' show listPrivileges;
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../ui/design_tokens.dart';
import '../../ui/money.dart';
import '../../ui/saved_notice.dart';
import '../../ui/screen_state.dart';
import '../common/form_feedback.dart';

Duration? _noRetry(int retryCount, Object error) => null;

final _privilegesAdminProvider = FutureProvider.autoDispose<List<Privilege>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listPrivileges(client, institution.id);
}, retry: _noRetry);

class PrivilegesScreen extends ConsumerStatefulWidget {
  const PrivilegesScreen({super.key});

  @override
  ConsumerState<PrivilegesScreen> createState() => _PrivilegesScreenState();
}

class _PrivilegesScreenState extends ConsumerState<PrivilegesScreen> {
  final _titleController = TextEditingController();
  final _descriptionController = TextEditingController();
  final _priceController = TextEditingController();
  final _stockController = TextEditingController();
  bool _isActive = true;
  bool _creating = false;
  ApiError? _createError;

  @override
  void dispose() {
    _titleController.dispose();
    _descriptionController.dispose();
    _priceController.dispose();
    _stockController.dispose();
    super.dispose();
  }

  Future<void> _handleCreate(String institutionId) async {
    setState(() {
      _creating = true;
      _createError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      final description = _descriptionController.text.trim();
      final stock = _stockController.text.trim();
      await createPrivilege(
        client,
        institutionId,
        CreatePrivilegeInput(
          title: _titleController.text,
          description: description.isEmpty ? null : description,
          price: int.tryParse(_priceController.text.trim()) ?? 0,
          stock: stock.isEmpty ? null : int.tryParse(stock),
          isActive: _isActive,
        ),
      );
      _titleController.clear();
      _descriptionController.clear();
      _priceController.clear();
      _stockController.clear();
      if (!mounted) return;
      setState(() => _isActive = true);
      ref.invalidate(_privilegesAdminProvider);
      showSavedNotice(context);
    } catch (error) {
      if (!mounted) return;
      setState(() => _createError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final institution = ref.watch(sessionProvider.select((state) => state.institution));
    final currencyName = institution?.currencyName;
    final privilegesAsync = ref.watch(_privilegesAdminProvider);
    final createFieldErrors = _createError?.fieldErrors;

    return Scaffold(
      appBar: AppBar(title: Text('Каталог', style: Theme.of(context).textTheme.titleMedium)),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            final _ = await ref.refresh(_privilegesAdminProvider.future);
          } catch (_) {
            // Ошибка показывается на месте ниже.
          }
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            Text('Новая позиция', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: AppSpacing.sm),
            TextField(
              controller: _titleController,
              enabled: !_creating,
              maxLength: 100,
              decoration: const InputDecoration(labelText: 'Название'),
            ),
            FieldErrorText(createFieldErrors?['title']),
            TextField(
              controller: _descriptionController,
              enabled: !_creating,
              maxLength: 500,
              decoration: const InputDecoration(labelText: 'Описание (необязательно)'),
            ),
            FieldErrorText(createFieldErrors?['description']),
            TextField(
              controller: _priceController,
              enabled: !_creating,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                labelText: currencyName != null ? 'Цена (в «$currencyName»)' : 'Цена',
              ),
            ),
            FieldErrorText(createFieldErrors?['price']),
            TextField(
              controller: _stockController,
              enabled: !_creating,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Остаток (пусто — без ограничения)'),
            ),
            FieldErrorText(createFieldErrors?['stock']),
            CheckboxListTile(
              value: _isActive,
              onChanged: _creating ? null : (value) => setState(() => _isActive = value ?? true),
              title: const Text('Активна'),
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
            ),
            FormErrorText(_createError == null ? null : messageForError(_createError!)),
            const SizedBox(height: AppSpacing.xs),
            OutlinedButton(
              onPressed: (_creating || institution == null) ? null : () => _handleCreate(institution.id),
              child: Text(_creating ? 'Создаём…' : 'Добавить позицию'),
            ),
            const SizedBox(height: AppSpacing.xl),
            Text('Позиции', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: AppSpacing.sm),
            privilegesAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) => ScreenStateError(
                message: messageForError(error),
                code: error is ApiError ? error.code : null,
                onRetry: () => ref.invalidate(_privilegesAdminProvider),
              ),
              data: (privileges) {
                if (privileges.isEmpty) {
                  return const ScreenStateEmpty(message: 'Позиций пока нет');
                }
                return Column(
                  children: [
                    for (final privilege in privileges)
                      _PrivilegeEditCard(
                        key: ValueKey(privilege.id),
                        privilege: privilege,
                        currencyName: currencyName,
                        institutionId: institution?.id,
                      ),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _PrivilegeEditCard extends ConsumerStatefulWidget {
  const _PrivilegeEditCard({super.key, required this.privilege, required this.currencyName, required this.institutionId});

  final Privilege privilege;
  final String? currencyName;
  final String? institutionId;

  @override
  ConsumerState<_PrivilegeEditCard> createState() => _PrivilegeEditCardState();
}

class _PrivilegeEditCardState extends ConsumerState<_PrivilegeEditCard> {
  late final TextEditingController _titleController;
  late final TextEditingController _descriptionController;
  late final TextEditingController _priceController;
  late final TextEditingController _stockController;
  late bool _isActive;
  bool _saving = false;
  ApiError? _saveError;

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(text: widget.privilege.title);
    _descriptionController = TextEditingController(text: widget.privilege.description ?? '');
    _priceController = TextEditingController(text: widget.privilege.price.toString());
    _stockController = TextEditingController(text: widget.privilege.stock?.toString() ?? '');
    _isActive = widget.privilege.isActive;
  }

  @override
  void dispose() {
    _titleController.dispose();
    _descriptionController.dispose();
    _priceController.dispose();
    _stockController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final institutionId = widget.institutionId;
    if (institutionId == null || _saving) return;

    final privilege = widget.privilege;
    final title = _titleController.text.trim();
    final description = _descriptionController.text.trim();
    final priceText = _priceController.text.trim();
    final stockText = _stockController.text.trim();
    final price = int.tryParse(priceText) ?? privilege.price;
    final stock = stockText.isEmpty ? null : int.tryParse(stockText);

    final input = UpdatePrivilegeInput(
      title: title != privilege.title ? title : null,
      description: description == (privilege.description ?? '') ? unsetField : (description.isEmpty ? null : description),
      price: price != privilege.price ? price : null,
      stock: stock != privilege.stock ? stock : unsetField,
      isActive: _isActive != privilege.isActive ? _isActive : null,
    );

    setState(() {
      _saving = true;
      _saveError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      await updatePrivilege(client, institutionId, privilege.id, input);
      ref.invalidate(_privilegesAdminProvider);
      if (!mounted) return;
      showSavedNotice(context);
    } catch (error) {
      if (!mounted) return;
      setState(() => _saveError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final fieldErrors = _saveError?.fieldErrors;
    final privilege = widget.privilege;

    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(privilege.title, style: const TextStyle(fontWeight: FontWeight.w600)),
                ),
                if (!privilege.isActive)
                  const Padding(
                    padding: EdgeInsets.only(left: AppSpacing.xs),
                    child: Text('Скрыта', style: TextStyle(color: AppColors.textMuted)),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            TextField(
              controller: _titleController,
              enabled: !_saving,
              maxLength: 100,
              decoration: const InputDecoration(labelText: 'Название'),
            ),
            FieldErrorText(fieldErrors?['title']),
            TextField(
              controller: _descriptionController,
              enabled: !_saving,
              maxLength: 500,
              decoration: const InputDecoration(labelText: 'Описание (необязательно)'),
            ),
            FieldErrorText(fieldErrors?['description']),
            TextField(
              controller: _priceController,
              enabled: !_saving,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                labelText: widget.currencyName != null ? 'Цена (в «${widget.currencyName}»)' : 'Цена',
              ),
            ),
            FieldErrorText(fieldErrors?['price']),
            TextField(
              controller: _stockController,
              enabled: !_saving,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Остаток (пусто — без ограничения)'),
            ),
            FieldErrorText(fieldErrors?['stock']),
            CheckboxListTile(
              value: _isActive,
              onChanged: _saving ? null : (value) => setState(() => _isActive = value ?? _isActive),
              title: const Text('Активна'),
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
            ),
            Row(
              children: [
                const Text('Сейчас: ', style: TextStyle(color: AppColors.textMuted)),
                Money(amount: privilege.price),
                if (widget.currencyName != null) ...[
                  const SizedBox(width: AppSpacing.xs),
                  Text(widget.currencyName!, style: const TextStyle(color: AppColors.textMuted)),
                ],
              ],
            ),
            FormErrorText(_saveError == null ? null : messageForError(_saveError!)),
            const SizedBox(height: AppSpacing.xs),
            Align(
              alignment: Alignment.centerRight,
              child: OutlinedButton(
                onPressed: _saving ? null : _save,
                child: Text(_saving ? 'Сохраняем…' : 'Сохранить'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
