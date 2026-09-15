// Самопроверка обвязки `staff_test_support.dart`: экран монтируется с сессией
// нужной роли, фейковый адаптер записывает тело запроса, а `remountScreen`
// пересобирает экран в том же `ProviderContainer` — тем самым проверяется,
// что провайдер пережил пересборку (без неё повторный запрос ушёл бы иначе).
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/admin/teachers_screen.dart';

import 'staff_test_support.dart';

void main() {
  testWidgets('pumpScreen монтирует заготовку с сессией admin, remountScreen пересобирает её', (tester) async {
    final adapter = RecordingAdapter(const {});
    final container = await pumpScreen(
      tester,
      const TeachersScreen(),
      adapter: adapter,
      session: adminSession(),
    );

    expect(find.text('Преподаватели'), findsWidgets);

    await remountScreen(tester, container, const TeachersScreen());

    expect(find.text('Преподаватели'), findsWidgets);
  });

  testWidgets('teacherSession и adminSession дают разные роли институту', (tester) async {
    final teacher = teacherSession();
    final admin = adminSession();

    expect(teacher.institution?.role.toJson(), 'teacher');
    expect(admin.institution?.role.toJson(), 'institution_admin');
  });
}
