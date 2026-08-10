import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'screens/method_screen.dart';
import 'theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
  ]);
  SystemChrome.setSystemUIOverlayStyle(SystemUiOverlayStyle.dark);

  List<CameraDescription> cameras = const [];
  try {
    cameras = await availableCameras();
  } catch (_) {
    cameras = const [];
  }

  runApp(FootMeasureApp(cameras: cameras));
}

class FootMeasureApp extends StatelessWidget {
  const FootMeasureApp({super.key, required this.cameras});

  final List<CameraDescription> cameras;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Foot Measure',
      debugShowCheckedModeBanner: false,
      theme: buildLightTheme(),
      home: MethodScreen(cameras: cameras),
    );
  }
}
