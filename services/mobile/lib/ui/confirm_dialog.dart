/// Диалог подтверждения — перенос `services/web/src/components/ConfirmDialog.tsx`.
/// При открытии фокус ставится на «Отмена» — безопасное действие для
/// опасных подтверждений.
library;

import 'package:flutter/material.dart';

import 'design_tokens.dart';

/// Показывает диалог подтверждения и возвращает `true`, если пользователь
/// подтвердил действие, иначе `false`/`null`.
Future<bool?> showConfirmDialog(
  BuildContext context, {
  required String title,
  String? description,
  required String confirmLabel,
  String cancelLabel = 'Отмена',
  bool danger = false,
}) {
  return showDialog<bool>(
    context: context,
    builder: (context) => _ConfirmDialog(
      title: title,
      description: description,
      confirmLabel: confirmLabel,
      cancelLabel: cancelLabel,
      danger: danger,
    ),
  );
}

class _ConfirmDialog extends StatefulWidget {
  const _ConfirmDialog({
    required this.title,
    required this.description,
    required this.confirmLabel,
    required this.cancelLabel,
    required this.danger,
  });

  final String title;
  final String? description;
  final String confirmLabel;
  final String cancelLabel;
  final bool danger;

  @override
  State<_ConfirmDialog> createState() => _ConfirmDialogState();
}

class _ConfirmDialogState extends State<_ConfirmDialog> {
  final _cancelFocusNode = FocusNode();

  @override
  void initState() {
    super.initState();
    // Фокус на «Отмена» сразу при открытии — аналог `cancelRef.current?.focus()` веба.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _cancelFocusNode.requestFocus();
    });
  }

  @override
  void dispose() {
    _cancelFocusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AppColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.lg),
        side: const BorderSide(color: AppColors.border),
      ),
      title: Text(widget.title, style: const TextStyle(color: AppColors.text)),
      content: widget.description != null
          ? Text(widget.description!, style: const TextStyle(color: AppColors.textMuted))
          : null,
      actions: [
        OutlinedButton(
          focusNode: _cancelFocusNode,
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(widget.cancelLabel),
        ),
        OutlinedButton(
          onPressed: () => Navigator.of(context).pop(true),
          style: widget.danger
              ? OutlinedButton.styleFrom(
                  foregroundColor: AppColors.danger,
                  side: const BorderSide(color: AppColors.danger),
                )
              : null,
          child: Text(widget.confirmLabel),
        ),
      ],
    );
  }
}
