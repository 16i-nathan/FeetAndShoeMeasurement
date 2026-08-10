import 'package:flutter_test/flutter_test.dart';

import 'package:foot_measure_lab/main.dart';

void main() {
  testWidgets('App builds', (tester) async {
    await tester.pumpWidget(const FootMeasureApp(cameras: []));
    // Production auto-routes to guidelines; allow a frame.
    await tester.pump();
    expect(find.byType(FootMeasureApp), findsOneWidget);
  });
}
