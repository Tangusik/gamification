/// Настройки учреждения (admin) — перенос
/// `services/web/src/pages/InstitutionSettingsPage.tsx`: переименование и
/// название валюты (В5/б); тип (`kind`) — только показывается.
///
/// После успеха — «Сохранено» на месте (без ухода с экрана) и
/// `reloadMemberships()`: без него новое название валюты не появится в
/// `sessionProvider.institution` и, соответственно, в остальных экранах до
/// следующего входа.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errors.dart';
import '../../api/institution_admin_api.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../i18n/labels.dart';
import '../../ui/design_tokens.dart';
import '../../ui/saved_notice.dart';
import '../../ui/screen_state.dart';
import '../common/form_feedback.dart';

Duration? _noRetry(int retryCount, Object error) => null;

final _institutionProvider = FutureProvider.autoDispose<Institution>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return getInstitution(client, institution.id);
}, retry: _noRetry);

class InstitutionSettingsScreen extends ConsumerStatefulWidget {
  const InstitutionSettingsScreen({super.key});

  @override
  ConsumerState<InstitutionSettingsScreen> createState() => _InstitutionSettingsScreenState();
}

class _InstitutionSettingsScreenState extends ConsumerState<InstitutionSettingsScreen> {
  final _nameController = TextEditingController();
  final _currencyNameController = TextEditingController();
  String? _loadedForId;
  Institution? _loaded;
  bool _saving = false;
  ApiError? _saveError;

  @override
  void dispose() {
    _nameController.dispose();
    _currencyNameController.dispose();
    super.dispose();
  }

  void _applyLoaded(Institution institution) {
    _loaded = institution;
    _nameController.text = institution.name;
    _currencyNameController.text = institution.currencyName ?? '';
  }

  Future<void> _handleSave() async {
    final loaded = _loaded;
    final institutionId = ref.read(sessionProvider).institution?.id;
    if (loaded == null || institutionId == null) return;

    final trimmedCurrencyName = _currencyNameController.text.trim();
    final nextCurrencyName = trimmedCurrencyName.isEmpty ? null : trimmedCurrencyName;
    final input = UpdateInstitutionInput(
      name: _nameController.text,
      currencyName: nextCurrencyName == loaded.currencyName ? unsetCurrencyName : nextCurrencyName,
    );

    setState(() {
      _saving = true;
      _saveError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      final updated = await updateInstitution(client, institutionId, input);
      if (!mounted) return;
      setState(() => _applyLoaded(updated));
      showSavedNotice(context);
      // Без reloadMemberships новая валюта не попадёт в sessionProvider —
      // остальные экраны продолжали бы показывать старое название до
      // следующего входа.
      unawaited(ref.read(sessionProvider.notifier).reloadMemberships());
    } catch (error) {
      if (!mounted) return;
      setState(() => _saveError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final institutionAsync = ref.watch(_institutionProvider);
    final fieldErrors = _saveError?.fieldErrors;

    return Scaffold(
      appBar: AppBar(title: Text('Настройки учреждения', style: Theme.of(context).textTheme.titleMedium)),
      body: institutionAsync.when(
        loading: () => const Padding(padding: EdgeInsets.all(AppSpacing.lg), child: ScreenStateLoading()),
        error: (error, _) => Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: ScreenStateError(
            message: messageForError(error),
            code: error is ApiError ? error.code : null,
            onRetry: () => ref.invalidate(_institutionProvider),
          ),
        ),
        data: (institution) {
          if (_loadedForId != institution.id) {
            _loadedForId = institution.id;
            _applyLoaded(institution);
          }
          return ListView(
            padding: const EdgeInsets.all(AppSpacing.lg),
            children: [
              TextField(
                controller: _nameController,
                enabled: !_saving,
                maxLength: 255,
                decoration: const InputDecoration(labelText: 'Название'),
              ),
              FieldErrorText(fieldErrors?['name']),
              TextField(
                controller: _currencyNameController,
                enabled: !_saving,
                maxLength: 32,
                decoration: const InputDecoration(labelText: 'Название валюты (пусто — по умолчанию)'),
              ),
              FieldErrorText(fieldErrors?['currency_name']),
              TextFormField(
                initialValue: kindLabels[institution.kind] ?? institution.kind.name,
                enabled: false,
                decoration: const InputDecoration(labelText: 'Тип'),
              ),
              FormErrorText(_saveError == null ? null : messageForError(_saveError!)),
              const SizedBox(height: AppSpacing.sm),
              OutlinedButton(
                onPressed: _saving ? null : _handleSave,
                child: Text(_saving ? 'Сохраняем…' : 'Сохранить'),
              ),
            ],
          );
        },
      ),
    );
  }
}
