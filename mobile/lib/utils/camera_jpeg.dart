import 'dart:typed_data';

import 'package:camera/camera.dart';
import 'package:image/image.dart' as img;

/// Convert a camera preview [CameraImage] to JPEG bytes (downscaled).
Uint8List? cameraImageToJpeg(CameraImage image, {int maxSide = 640, int quality = 70}) {
  try {
    final rgb = _toRgb(image);
    if (rgb == null) return null;
    var framed = rgb;
    final longSide = framed.width > framed.height ? framed.width : framed.height;
    if (longSide > maxSide) {
      final scale = maxSide / longSide;
      framed = img.copyResize(
        framed,
        width: (framed.width * scale).round(),
        height: (framed.height * scale).round(),
        interpolation: img.Interpolation.average,
      );
    }
    return Uint8List.fromList(img.encodeJpg(framed, quality: quality));
  } catch (_) {
    return null;
  }
}

img.Image? _toRgb(CameraImage image) {
  if (image.format.group == ImageFormatGroup.bgra8888) {
    return img.Image.fromBytes(
      width: image.width,
      height: image.height,
      bytes: image.planes[0].bytes.buffer,
      order: img.ChannelOrder.bgra,
    );
  }
  if (image.format.group == ImageFormatGroup.yuv420 ||
      image.planes.length >= 2) {
    return _yuv420ToImage(image);
  }
  return null;
}

img.Image _yuv420ToImage(CameraImage image) {
  final w = image.width;
  final h = image.height;
  final yPlane = image.planes[0];
  final uPlane = image.planes.length > 1 ? image.planes[1] : image.planes[0];
  final vPlane = image.planes.length > 2 ? image.planes[2] : uPlane;
  final out = img.Image(width: w, height: h);
  final yRow = yPlane.bytesPerRow;
  final uvRow = uPlane.bytesPerRow;
  final uvPix = uPlane.bytesPerPixel ?? 1;

  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      final yi = y * yRow + x;
      final yVal = yPlane.bytes[yi];
      final uvIndex = (y >> 1) * uvRow + (x >> 1) * uvPix;
      final u = uPlane.bytes[uvIndex.clamp(0, uPlane.bytes.length - 1)];
      final v = vPlane.bytes[uvIndex.clamp(0, vPlane.bytes.length - 1)];
      final r = (yVal + 1.370705 * (v - 128)).round().clamp(0, 255);
      final g = (yVal - 0.337633 * (u - 128) - 0.698001 * (v - 128))
          .round()
          .clamp(0, 255);
      final b = (yVal + 1.732446 * (u - 128)).round().clamp(0, 255);
      out.setPixelRgb(x, y, r, g, b);
    }
  }
  return out;
}
