import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/ui/pixel_sprite.dart';

void main() {
  testWidgets('рисуется без ошибок для всех спрайтов', (tester) async {
    for (final name in SpriteName.values) {
      await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: PixelSprite(name: name, size: 24))),
      );
      expect(find.byType(PixelSprite), findsOneWidget);
      expect(tester.takeException(), isNull);
    }
  });

  testWidgets('монета без переопределения цвета рисуется золотой палитрой', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: Scaffold(body: PixelSprite(name: SpriteName.coin))),
    );
    expect(tester.takeException(), isNull);
  });
}
