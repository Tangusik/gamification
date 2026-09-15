/// Riverpod-провайдер списка преподавателей учреждения (09b) — зеркало
/// `services/web/src/pages/TeachersPage.tsx`. Без кодогенерации, как у
/// `lib/screens/student/providers.dart`.
///
/// `.autoDispose`: данные не нужны, пока раздел «Преподаватели» не открыт.
/// Автоповтор Riverpod 3 отключён (`retry: _noRetry`) по той же причине, что
/// в `student/providers.dart`.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/teachers_api.dart';
import '../../auth/session.dart';

Duration? _noRetry(int retryCount, Object error) => null;

/// Все преподаватели текущего учреждения — доступно только `institution_admin`
/// (сервер отвечает 403, если роль другая; экран показывает
/// `ScreenStateForbidden`).
final teachersProvider = FutureProvider.autoDispose<List<InstitutionMember>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listTeachers(client, institution.id);
}, retry: _noRetry);
