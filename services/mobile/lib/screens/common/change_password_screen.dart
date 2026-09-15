/// Смена временного пароля — `/password`, зеркало
/// `services/web/src/pages/ChangePasswordPage.tsx`.
///
/// Пока у пользователя стоит `must_change_password`, роутер уводит сюда с
/// любого другого защищённого маршрута (`app_router.dart`). После успеха
/// форма сама кладёт обновлённого пользователя в сессию (`updateUser`), а
/// этот экран просто уходит на главную.
library;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../ui/design_tokens.dart';
import 'change_password_form.dart';

class ChangePasswordScreen extends StatelessWidget {
  const ChangePasswordScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Смена пароля')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Перед началом работы установите постоянный пароль вместо временного.'),
              const SizedBox(height: AppSpacing.md),
              ChangePasswordForm(onSuccess: (_) => context.go('/')),
            ],
          ),
        ),
      ),
    );
  }
}
