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
  /// Retries on the native side so a cold AR stack is less likely to false-negative.
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

  /// Brief AR session to wake sleeping Play Services for AR / LiDAR.
  /// Must not run while a Flutter [CameraController] holds the camera.
  static Future<void> warmUp() async {
    if (kIsWeb) return;
    if (!(Platform.isIOS || Platform.isAndroid)) return;
    try {
      await _channel.invokeMethod<dynamic>('warmUp');
    } on MissingPluginException {
      // Older builds without warmUp — ignore.
    } on PlatformException catch (e) {
      // Soft fail: capture path still retries.
      if (e.code == 'no_lidar' || e.code == 'no_depth') rethrow;
    }
  }

  /// Re-check support and wake AR before opening the depth camera flow.
  static Future<bool> prepareForCapture() async {
    final supported = await isSupported();
    if (!supported) return false;
    try {
      await warmUp();
    } on PlatformException catch (e) {
      if (e.code == 'no_lidar' || e.code == 'no_depth') return false;
      // camera_busy / timeout on warm-up — still allow Capture to try.
    }
    // Second probe after wake — reduces "unavailable until other AR app" cases.
    return isSupported();
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

  /// Warm-up + capture with auto-retry for cold / sleeping AR.
  static Future<DepthFrame> captureWithRetry({int attempts = 3}) async {
    Object? last;
    for (var i = 0; i < attempts; i++) {
      try {
        if (i > 0) {
          await Future<void>.delayed(Duration(milliseconds: 450 * i));
          try {
            await warmUp();
          } catch (_) {}
        }
        return await capture();
      } on PlatformException catch (e) {
        last = e;
        final retryable = e.code == 'timeout' ||
            e.code == 'camera_busy' ||
            e.code == 'busy' ||
            e.code == 'error';
        final hardFail =
            e.code == 'no_lidar' || e.code == 'no_depth' || e.code == 'arcore';
        if (hardFail || !retryable || i == attempts - 1) rethrow;
      } catch (e) {
        last = e;
        if (i == attempts - 1) rethrow;
      }
    }
    if (last is Exception) throw last;
    throw PlatformException(code: 'error', message: '$last');
  }

  static String friendlyMessage(PlatformException e) {
    switch (e.code) {
      case 'camera_busy':
        return e.message ??
            'Camera still in use. Wait a second and tap Capture again.';
      case 'timeout':
        return e.message ??
            'Depth sensor still waking. Hold steady and retry.';
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
