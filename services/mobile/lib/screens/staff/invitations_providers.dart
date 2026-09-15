/// Riverpod-провайдер списка приглашений учреждения (09b) — зеркало
/// `services/web/src/pages/InvitationsPage.tsx`.
///
/// `institution_admin` видит все приглашения учреждения, `teacher` — только
/// свои: список фильтрует сервер (`ListInvitations` по `created_by`, F3
/// `.claude/knowledge/gamification-service/03-invitations.md`), клиент здесь
/// ничего не урезает и не должен — тот же принцип, что и в вебе.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/institution_admin_api.dart';
import '../../auth/session.dart';

Duration? _noRetry(int retryCount, Object error) => null;

final invitationsProvider = FutureProvider.autoDispose<List<InvitationRead>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listInvitations(client, institution.id);
}, retry: _noRetry);
