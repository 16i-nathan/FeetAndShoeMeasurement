import 'dart:typed_data';

/// Minimal NumPy `.npy` writer for little-endian float32 2D arrays.
Uint8List encodeFloat32Npy(Float32List data, int height, int width) {
  if (data.length != height * width) {
    throw ArgumentError('data length ${data.length} != $height x $width');
  }
  final headerDict =
      "{'descr': '<f4', 'fortran_order': False, 'shape': ($height, $width), }";
  // magic(6) + ver(2) + header_len(2) + header + data; header padded to 16-byte align
  const prefixLen = 10; // \x93NUMPY + 1 + 0 + uint16 len
  var header = headerDict;
  var total = prefixLen + header.length + 1; // + newline
  final pad = (16 - (total % 16)) % 16;
  header = '$header${' ' * pad}\n';

  final headerBytes = Uint8List.fromList(header.codeUnits);
  final out = BytesBuilder(copy: false);
  out.add([0x93, 0x4E, 0x55, 0x4D, 0x50, 0x59, 0x01, 0x00]);
  final len = ByteData(2)..setUint16(0, headerBytes.length, Endian.little);
  out.add(len.buffer.asUint8List());
  out.add(headerBytes);
  out.add(data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes));
  return out.toBytes();
}
