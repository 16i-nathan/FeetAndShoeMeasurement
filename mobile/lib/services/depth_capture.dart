import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../utils/npy.dart';

class DepthFrame {
  DepthFrame({
    required this.jpegBytes,
    required this.depthNpyBytes,
    required this.width,
    required this.height,
    this.fx,
    this.fy,
    this.cx,
    this.cy,
  });

  final Uint8List jpegBytes;
  final Uint8List depthNpyBytes;
  final int width;
  final int height;
  final double? fx;
  final double? fy;
  final double? cx;
  final double? cy;
}

class DepthCapture {
  static const _channel = MethodChannel('foot_measure_lab/depth');

  /// True when this physical device can capture metric scene depth.
  static Future<bool> isSupported() async {
    if (kIsWeb) return false;
    if (!(Platform.isIOS || Platform.isAndroid)) return false;
    try {
      final v = await _channel.invokeMethod<bool>('isSupported');
      return v == true;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  /// Captures one RGB JPEG + metric depth (meters) as `.npy`.
  ///
  /// Caller must release any Flutter [CameraController] first — ARCore/ARKit
  /// cannot share the camera with the `camera` plugin.
  static Future<DepthFrame> capture() async {
    try {
      final raw = await _channel.invokeMethod<dynamic>('capture');
      if (raw is! Map) {
        throw PlatformException(code: 'null', message: 'Empty depth capture');
      }
      final map = Map<String, dynamic>.from(raw);
      final jpeg = map['jpeg'] as Uint8List;
      final depthBytes = map['depth'] as Uint8List;
      final w = map['width'] as int;
      final h = map['height'] as int;

      final floats = Float32List(w * h);
      final bd = ByteData.sublistView(depthBytes);
      for (var i = 0; i < floats.length; i++) {
        floats[i] = bd.getFloat32(i * 4, Endian.little);
      }

      return DepthFrame(
        jpegBytes: jpeg,
        depthNpyBytes: encodeFloat32Npy(floats, h, w),
        width: w,
        height: h,
        fx: (map['fx'] as num?)?.toDouble(),
        fy: (map['fy'] as num?)?.toDouble(),
        cx: (map['cx'] as num?)?.toDouble(),
        cy: (map['cy'] as num?)?.toDouble(),
      );
    } on PlatformException catch (e) {
      throw PlatformException(
        code: e.code,
        message: friendlyMessage(e),
        details: e.details,
      );
    }
  }

  static String friendlyMessage(PlatformException e) {
    switch (e.code) {
      case 'camera_busy':
        return e.message ??
            'Camera still in use. Wait a second and tap Capture again.';
      case 'timeout':
        return e.message ??
            'Depth sensor timed out. Hold the phone steady over the floor.';
      case 'busy':
        return 'Depth capture already running — wait and retry.';
      case 'arcore':
        return e.message ?? 'Install or update Google Play Services for AR.';
      case 'no_depth':
      case 'no_lidar':
        return e.message ?? 'This phone cannot capture metric depth.';
      default:
        return e.message ?? 'Depth capture failed (${e.code}).';
    }
  }
}
