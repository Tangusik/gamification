/// Форма создания учреждения — общая для Профиля и онбординга «Мои
/// учреждения», зеркало `services/web/src/components/InstitutionCreateForm.tsx`.
///
/// Что делать после успешного создания, решает вызывающий экран через
/// [onCreated]: Профиль перечитывает членства и не переключает учреждение,
/// онбординг сразу делает созданное учреждение текущим.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/auth_api.dart' show InstitutionKind;
import '../../api/errors.dart';
import '../../api/institutions_api.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../i18n/labels.dart';
import '../../ui/design_tokens.dart';
import 'form_feedback.dart';

class InstitutionCreateForm extends ConsumerStatefulWidget {
  const InstitutionCreateForm({super.key, required this.onCreated, this.submitLabel = 'Создать учреждение'});

  /// Вызывается после успешного создания с id нового учреждения.
  final Future<void> Function(String institutionId) onCreated;
  final String submitLabel;

  @override
  ConsumerState<InstitutionCreateForm> createState() => _InstitutionCreateFormState();
}

class _InstitutionCreateFormState extends ConsumerState<InstitutionCreateForm> {
  final _nameController = TextEditingController();
  InstitutionKind _kind = InstitutionKind.school;
  bool _pending = false;
  ApiError? _error;

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _pending = true;
      _error = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      final id = await createInstitution(client, name: _nameController.text, kind: _kind);
      _nameController.clear();
      if (mounted) setState(() => _kind = InstitutionKind.school);
      await widget.onCreated(id);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _pending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          controller: _nameController,
          enabled: !_pending,
          maxLength: 255,
          decoration: const InputDecoration(labelText: 'Название учреждения'),
        ),
        DropdownButtonFormField<InstitutionKind>(
          initialValue: _kind,
          decoration: const InputDecoration(labelText: 'Тип'),
          onChanged: _pending ? null : (value) => setState(() => _kind = value ?? InstitutionKind.school),
          items: [
            for (final kind in InstitutionKind.values)
              DropdownMenuItem(value: kind, child: Text(kindLabels[kind] ?? kind.name)),
          ],
        ),
        FormErrorText(_error == null ? null : messageForError(_error!)),
        const SizedBox(height: AppSpacing.sm),
        OutlinedButton(
          onPressed: _pending ? null : _submit,
          child: Text(_pending ? 'Создаём…' : widget.submitLabel),
        ),
      ],
    );
  }
}
