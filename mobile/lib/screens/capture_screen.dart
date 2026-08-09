import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';

import '../api/measure_api.dart';
import '../config.dart';

class CaptureScreen extends StatefulWidget {
  const CaptureScreen({super.key, required this.cameras});

  final List<CameraDescription> cameras;

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen> {
  final _api = MeasureApi();

  CameraController? _controller;
  String _mode = 'card';
  bool _ready = false;
  String _statusText = 'Starting camera…';
  String _message = 'Allow camera access to begin.';
  List<String> _hints = const [];
  bool _busy = false;
  bool _processing = false;
  Timer? _validateTimer;
  MeasureResult? _result;
  String? _error;

  static const _bg = Color(0xFF1A1410);
  static const _panel = Color(0xFF2A211C);
  static const _ink = Color(0xFFF4EBE3);
  static const _muted = Color(0xFFB8A99A);
  static const _readyColor = Color(0xFF3DBE7A);
  static const _waitColor = Color(0xFFE0A23A);
  static const _accent = Color(0xFFF0C27A);

  @override
  void initState() {
    super.initState();
    _initCamera();
  }

  @override
  void dispose() {
    _validateTimer?.cancel();
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _initCamera() async {
    final cam = await Permission.camera.request();
    if (!cam.isGranted) {
      setState(() {
        _statusText = 'Camera blocked';
        _message = 'Enable camera permission in settings.';
      });
      return;
    }
    if (widget.cameras.isEmpty) {
      setState(() {
        _statusText = 'No camera';
        _message = 'No camera found on this device.';
      });
      return;
    }

    final back = widget.cameras.firstWhere(
      (c) => c.lensDirection == CameraLensDirection.back,
      orElse: () => widget.cameras.first,
    );

    final controller = CameraController(
      back,
      ResolutionPreset.high,
      enableAudio: false,
      imageFormatGroup: ImageFormatGroup.jpeg,
    );
    try {
      await controller.initialize();
      if (!mounted) return;
      setState(() {
        _controller = controller;
        _statusText = 'Aligning…';
        _message = 'Point top-down at foot + credit card.';
      });
      _validateTimer = Timer.periodic(
        const Duration(milliseconds: 1600),
        (_) => _validateLoop(),
      );
    } catch (e) {
      setState(() {
        _statusText = 'Camera error';
        _message = '$e';
      });
    }
  }

  Future<void> _validateLoop() async {
    if (_busy || _processing) return;
    final c = _controller;
    if (c == null || !c.value.isInitialized) return;

    _busy = true;
    try {
      final file = await c.takePicture();
      final bytes = await file.readAsBytes();
      try {
        await File(file.path).delete();
      } catch (_) {}
      final result = await _api.validateFrame(Uint8List.fromList(bytes), _mode);
      if (!mounted || _processing) return;
      setState(() {
        _ready = result.ready;
        _statusText = result.ready ? 'Ready' : 'Not ready';
        _message = result.message;
        _hints = result.hints;
      });
    } catch (e) {
      if (!mounted || _processing) return;
      setState(() {
        _ready = false;
        _statusText = 'Checking…';
        _message = 'API unreachable ($apiBaseUrl). Is the server running?';
      });
    } finally {
      _busy = false;
    }
  }

  Future<void> _capture() async {
    final c = _controller;
    if (c == null || !c.value.isInitialized || _processing) return;

    setState(() {
      _processing = true;
      _result = null;
      _error = null;
      _statusText = 'Captured';
      _message = 'Measuring in the background…';
    });
    _validateTimer?.cancel();

    try {
      final file = await c.takePicture();
      final bytes = await file.readAsBytes();
      final jobId = await _api.createJob(Uint8List.fromList(bytes), _mode);
      final job = await _api.waitForJob(jobId);
      if (!mounted) return;

      if (job.status == 'error') {
        setState(() {
          _error = job.error ?? 'Measurement failed';
          _message = _error!;
          _statusText = 'Failed';
        });
      } else if (job.status == 'awaiting_depth') {
        setState(() {
          _error =
              'Depth mode needs a native LiDAR export. Use Credit card mode instead.';
          _message = _error!;
          _statusText = 'Use card mode';
        });
      } else if (job.result != null) {
        setState(() {
          _result = job.result;
          _statusText = 'Done';
          _message = 'Mode: ${job.mode}';
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = '$e';
        _statusText = 'Failed';
        _message = _error!;
      });
    }
  }

  void _retake() {
    setState(() {
      _processing = false;
      _result = null;
      _error = null;
      _ready = false;
      _statusText = 'Aligning…';
      _message = 'Point top-down at foot + reference.';
    });
    _validateTimer?.cancel();
    _validateTimer = Timer.periodic(
      const Duration(milliseconds: 1600),
      (_) => _validateLoop(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = _controller;
    return Scaffold(
      backgroundColor: _bg,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
          children: [
            Text(
              'Foot Measure Lab',
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                    color: _ink,
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.5,
                  ),
            ),
            const SizedBox(height: 6),
            const Text(
              'Line up until Ready, then capture. Measurement runs in the background.',
              style: TextStyle(color: _muted, height: 1.35),
            ),
            const SizedBox(height: 16),
            AspectRatio(
              aspectRatio: 3 / 4,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(18),
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    if (c != null && c.value.isInitialized)
                      CameraPreview(c)
                    else
                      const ColoredBox(
                        color: Colors.black,
                        child: Center(
                          child: CircularProgressIndicator(color: _accent),
                        ),
                      ),
                    DecoratedBox(
                      decoration: BoxDecoration(
                        border: Border.all(
                          color: _ready ? _readyColor : _waitColor,
                          width: 2.5,
                        ),
                      ),
                    ),
                    Positioned(
                      left: 12,
                      top: 12,
                      child: _StatusPill(
                        ready: _ready && !_processing,
                        text: _statusText,
                        readyColor: _readyColor,
                        waitColor: _waitColor,
                      ),
                    ),
                    Positioned(
                      left: 12,
                      right: 12,
                      bottom: 12,
                      child: Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: _bg.withValues(alpha: 0.55),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                            color: _ink.withValues(alpha: 0.16),
                          ),
                        ),
                        child: Text(
                          _message,
                          style: const TextStyle(color: _ink, fontSize: 14),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 14),
            DropdownButtonFormField<String>(
              initialValue: _mode,
              dropdownColor: _panel,
              style: const TextStyle(color: _ink),
              decoration: InputDecoration(
                labelText: 'Mode',
                labelStyle: const TextStyle(color: _muted),
                filled: true,
                fillColor: _panel,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
              items: const [
                DropdownMenuItem(value: 'card', child: Text('Credit card')),
                DropdownMenuItem(value: 'paper', child: Text('A4 paper')),
                DropdownMenuItem(value: 'both', child: Text('Paper + card')),
                DropdownMenuItem(
                  value: 'depth',
                  child: Text('Depth / LiDAR'),
                ),
              ],
              onChanged: _processing
                  ? null
                  : (v) {
                      if (v == null) return;
                      setState(() {
                        _mode = v;
                        _ready = false;
                        _statusText = 'Aligning…';
                        _message = v == 'depth'
                            ? 'Depth needs a LiDAR/AR depth map — phone camera alone is not enough. Prefer Credit card.'
                            : 'Mode changed — re-check framing.';
                      });
                    },
            ),
            if (_mode == 'depth') ...[
              const SizedBox(height: 8),
              Text(
                'Depth / LiDAR: Flutter cannot read phone LiDAR from the normal camera. '
                'Capture will save RGB only unless you later attach a depth export via the API. '
                'For testers, use Credit card mode.',
                style: TextStyle(
                  color: _muted.withValues(alpha: 0.95),
                  fontSize: 12,
                  height: 1.35,
                ),
              ),
            ],
            const SizedBox(height: 12),
            if (!_processing)
              FilledButton(
                onPressed: (_controller?.value.isInitialized ?? false)
                    ? _capture
                    : null,
                style: FilledButton.styleFrom(
                  backgroundColor: _accent,
                  foregroundColor: _bg,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
                child: Text(
                  _ready ? 'Capture (Ready)' : 'Capture anyway',
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 16,
                  ),
                ),
              )
            else
              OutlinedButton(
                onPressed: _retake,
                style: OutlinedButton.styleFrom(
                  foregroundColor: _ink,
                  side: BorderSide(color: _ink.withValues(alpha: 0.25)),
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
                child: const Text('Retake'),
              ),
            if (_hints.isNotEmpty && !_processing) ...[
              const SizedBox(height: 12),
              ..._hints.map(
                (h) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text('• $h', style: const TextStyle(color: _muted)),
                ),
              ),
            ],
            if (_processing) ...[
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: _panel,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: _ink.withValues(alpha: 0.16)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _result != null
                          ? 'Result'
                          : (_error != null ? 'Could not measure' : 'Processing'),
                      style: const TextStyle(
                        color: _ink,
                        fontWeight: FontWeight.w800,
                        fontSize: 18,
                      ),
                    ),
                    const SizedBox(height: 8),
                    if (_result == null && _error == null)
                      const LinearProgressIndicator(
                        color: _accent,
                        backgroundColor: Colors.black26,
                      ),
                    if (_error != null)
                      Text(_error!, style: const TextStyle(color: Color(0xFFE25B4A))),
                    if (_result != null) ...[
                      const SizedBox(height: 8),
                      _MetricsGrid(result: _result!),
                    ],
                  ],
                ),
              ),
            ],
            const SizedBox(height: 16),
            Text(
              'API: $apiBaseUrl',
              style: TextStyle(
                color: _muted.withValues(alpha: 0.8),
                fontSize: 11,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({
    required this.ready,
    required this.text,
    required this.readyColor,
    required this.waitColor,
  });

  final bool ready;
  final String text;
  final Color readyColor;
  final Color waitColor;

  @override
  Widget build(BuildContext context) {
    final color = ready ? readyColor : waitColor;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: const Color(0xFF1A1410).withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: Colors.white24),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 8),
          Text(
            text,
            style: const TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w700,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }
}

class _MetricsGrid extends StatelessWidget {
  const _MetricsGrid({required this.result});

  final MeasureResult result;

  @override
  Widget build(BuildContext context) {
    final items = [
      ('${result.cm} cm', 'Foot length'),
      ('${result.eu}', 'EU (approx)'),
      ('${result.usMen}', 'US Men'),
      ('${result.usWomen}', 'US Women'),
    ];
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: 8,
      crossAxisSpacing: 8,
      childAspectRatio: 1.7,
      children: [
        for (final item in items)
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.black26,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  item.$1,
                  style: const TextStyle(
                    color: Color(0xFFF4EBE3),
                    fontWeight: FontWeight.w800,
                    fontSize: 20,
                  ),
                ),
                Text(
                  item.$2,
                  style: const TextStyle(color: Color(0xFFB8A99A), fontSize: 12),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
