import 'package:flutter_test/flutter_test.dart';
import 'package:foot_measure_lab/main.dart';

void main() {
  testWidgets('method screen builds', (tester) async {
    await tester.pumpWidget(const FootMeasureApp(cameras: []));
    expect(find.text('Foot Measure'), findsOneWidget);
    expect(find.text('Credit card'), findsOneWidget);
  });
}
