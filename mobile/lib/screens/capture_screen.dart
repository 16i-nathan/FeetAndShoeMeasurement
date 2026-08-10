import 'dart:async';
import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';

import '../api/measure_api.dart';
import '../config.dart';
import '../models/measure_method.dart';
import '../services/depth_capture.dart';
import '../theme/app_theme.dart';
import 'result_screen.dart';

class CaptureScreen extends StatefulWidget {
  const CaptureScreen({
    super.key,
    required this.cameras,
    required this.method,
    required this.depthSupported,
  });

  final List<CameraDescription> cameras;
  final MeasureMethod method;
  final bool depthSupported;

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen> {
  final _api = MeasureApi();

  CameraController? _controller;
  bool _ready = false;
  int _readyStreak = 0;
  String _statusText = 'Starting camera…';
  String _message = 'Allow camera access to begin.';
  List<String> _hints = const [];
  Map<String, bool> _checks = const {};
  List<String> _errors = const [];
  bool _busy = false;
  bool _processing = false;
  Timer? _validateTimer;

  static const _readyHoldNeeded = 2; // ~2 successful polls

  String get _mode => widget.method.id;

  @override
  void initState() {
    super.initState();
    SystemChrome.setSystemUIOverlayStyle(SystemUiOverlayStyle.dark);
    if (_mode == 'depth' && !widget.depthSupported) {
      setState(() {
        _statusText = 'No LiDAR';
        _message =
            'This device cannot capture depth. Go back and choose Credit card.';
      });
    }
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
        _message = 'No camera found. Use a physical phone, not browser emulation.';
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
        _statusText = _mode == 'depth' && !widget.depthSupported
            ? 'No LiDAR'
            : 'Aligning…';
        _message = _mode == 'depth' && !widget.depthSupported
            ? 'This device cannot capture depth.'
            : 'Follow the guide — capture unlocks when Ready.';
      });
      if (!(_mode == 'depth' && !widget.depthSupported)) {
        _validateTimer = Timer.periodic(
          const Duration(milliseconds: 1400),
          (_) => _validateLoop(),
        );
      }
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

      final streak = result.ready ? _readyStreak + 1 : 0;
      final lockedIn = streak >= _readyHoldNeeded;
      setState(() {
        _readyStreak = streak;
        _ready = lockedIn;
        _statusText = lockedIn
            ? 'Ready'
            : (result.ready ? 'Hold steady…' : 'Not ready');
        _message = lockedIn
            ? 'Looking good — tap Capture'
            : result.message;
        _hints = result.hints;
        _checks = result.checks;
        _errors = result.errors;
      });
    } catch (e) {
      if (!mounted || _processing) return;
      setState(() {
        _ready = false;
        _readyStreak = 0;
        _statusText = 'Checking…';
        _message = 'API unreachable ($apiBaseUrl). Start the server first.';
      });
    } finally {
      _busy = false;
    }
  }

  bool get _canCapture {
    if (_processing) return false;
    if (_mode == 'depth' && !widget.depthSupported) return false;
    return _ready && (_controller?.value.isInitialized ?? false);
  }

  Future<void> _capture() async {
    if (!_canCapture) return;

    setState(() {
      _processing = true;
      _statusText = 'Captured';
      _message = _mode == 'depth'
          ? 'Capturing LiDAR depth…'
          : 'Measuring securely in the background…';
    });
    _validateTimer?.cancel();

    try {
      late final String jobId;
      if (_mode == 'depth') {
        final frame = await DepthCapture.capture();
        if (!mounted) return;
        setState(() => _message = 'Depth captured — measuring…');
        jobId = await _api.createJob(
          frame.jpegBytes,
          'depth',
          depthNpy: frame.depthNpyBytes,
          fx: frame.fx,
          fy: frame.fy,
          cx: frame.cx,
          cy: frame.cy,
        );
      } else {
        final c = _controller!;
        final file = await c.takePicture();
        final bytes = await file.readAsBytes();
        jobId = await _api.createJob(Uint8List.fromList(bytes), _mode);
      }

      final job = await _api.waitForJob(jobId);
      if (!mounted) return;

      if (job.status == 'done' && job.result != null) {
        await Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => ResultScreen(
              result: job.result!,
              mode: job.mode,
              cameras: widget.cameras,
            ),
          ),
        );
        return;
      }

      setState(() {
        _processing = false;
        _ready = false;
        _readyStreak = 0;
        _statusText = 'Blocked';
        _message = job.error ??
            job.message ??
            'Measurement failed quality checks. Retake with the guidelines.';
      });
      _restartValidation();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _processing = false;
        _ready = false;
        _readyStreak = 0;
        _statusText = 'Failed';
        _message = '$e';
      });
      _restartValidation();
    }
  }

  void _restartValidation() {
    if (_mode == 'depth' && !widget.depthSupported) return;
    _validateTimer?.cancel();
    _validateTimer = Timer.periodic(
      const Duration(milliseconds: 1400),
      (_) => _validateLoop(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = _controller;
    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        title: Text(widget.method.title),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Guidelines'),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 28),
        children: [
          AspectRatio(
            aspectRatio: 3 / 4,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(20),
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (c != null && c.value.isInitialized)
                    CameraPreview(c)
                  else
                    Container(
                      color: const Color(0xFF111827),
                      child: const Center(
                        child: CircularProgressIndicator(
                          color: AppColors.primary,
                        ),
                      ),
                    ),
                  IgnorePointer(
                    child: CustomPaint(
                      painter: _GuidePainter(ready: _ready),
                    ),
                  ),
                  Positioned(
                    left: 12,
                    top: 12,
                    child: _Pill(
                      ready: _ready,
                      text: _statusText,
                    ),
                  ),
                  Positioned(
                    left: 12,
                    right: 12,
                    bottom: 12,
                    child: Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.92),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: AppColors.line),
                      ),
                      child: Text(
                        _message,
                        style: const TextStyle(
                          color: AppColors.ink,
                          fontWeight: FontWeight.w600,
                          height: 1.3,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 14),
          _CheckGrid(checks: _checks),
          if (_hints.isNotEmpty) ...[
            const SizedBox(height: 10),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppColors.dangerSoft,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Fix before capture',
                    style: TextStyle(
                      fontWeight: FontWeight.w800,
                      color: AppColors.danger,
                    ),
                  ),
                  const SizedBox(height: 6),
                  ..._hints.map(
                    (h) => Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text('• $h',
                          style: const TextStyle(color: AppColors.ink)),
                    ),
                  ),
                  if (_errors.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 6,
                      children: _errors
                          .map(
                            (e) => Chip(
                              label: Text(e, style: const TextStyle(fontSize: 11)),
                              visualDensity: VisualDensity.compact,
                              backgroundColor: Colors.white,
                              side: const BorderSide(color: AppColors.danger),
                            ),
                          )
                          .toList(),
                    ),
                  ],
                ],
              ),
            ),
          ],
          const SizedBox(height: 14),
          FilledButton(
            onPressed: _canCapture && !_processing ? _capture : null,
            child: Text(
              _processing
                  ? 'Working…'
                  : (_canCapture ? 'Capture' : 'Waiting for Ready'),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            _canCapture
                ? 'Quality checks passed. Capture will be rejected again if measurement fails.'
                : 'Capture is locked until all checks are green. This prevents bad results.',
            textAlign: TextAlign.center,
            style: const TextStyle(color: AppColors.muted, fontSize: 12, height: 1.35),
          ),
        ],
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.ready, required this.text});

  final bool ready;
  final String text;

  @override
  Widget build(BuildContext context) {
    final color = ready ? AppColors.ready : AppColors.wait;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.95),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.5)),
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
            style: TextStyle(
              color: AppColors.ink,
              fontWeight: FontWeight.w800,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }
}

class _CheckGrid extends StatelessWidget {
  const _CheckGrid({required this.checks});

  final Map<String, bool> checks;

  static const labels = <String, String>{
    'brightness': 'Light',
    'sharpness': 'Focus',
    'no_glare': 'No glare',
    'reference': 'Reference',
    'full_frame': 'Full frame',
    'content': 'Foot',
    'contrast': 'Floor',
  };

  @override
  Widget build(BuildContext context) {
    final keys = labels.keys.where((k) => checks.containsKey(k)).toList();
    if (keys.isEmpty) {
      return const SizedBox.shrink();
    }
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final k in keys)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
            decoration: BoxDecoration(
              color: (checks[k] == true)
                  ? AppColors.primarySoft
                  : AppColors.dangerSoft,
              borderRadius: BorderRadius.circular(999),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  checks[k] == true ? Icons.check : Icons.close,
                  size: 14,
                  color: checks[k] == true ? AppColors.ready : AppColors.danger,
                ),
                const SizedBox(width: 4),
                Text(
                  labels[k]!,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: AppColors.ink,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _GuidePainter extends CustomPainter {
  _GuidePainter({required this.ready});

  final bool ready;

  @override
  void paint(Canvas canvas, Size size) {
    final border = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..color = ready ? AppColors.ready : Colors.white70;
    final r = RRect.fromRectAndRadius(
      Rect.fromLTWH(14, 14, size.width - 28, size.height - 28),
      const Radius.circular(18),
    );
    canvas.drawRRect(r, border);

    // Foot guide + card placeholder
    final guide = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6
      ..color = Colors.white.withValues(alpha: 0.55);
    final foot = Path()
      ..moveTo(size.width * 0.38, size.height * 0.78)
      ..quadraticBezierTo(
        size.width * 0.28,
        size.height * 0.55,
        size.width * 0.40,
        size.height * 0.28,
      )
      ..quadraticBezierTo(
        size.width * 0.50,
        size.height * 0.40,
        size.width * 0.52,
        size.height * 0.62,
      )
      ..quadraticBezierTo(
        size.width * 0.50,
        size.height * 0.74,
        size.width * 0.38,
        size.height * 0.78,
      );
    canvas.drawPath(foot, guide);
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(
          size.width * 0.58,
          size.height * 0.48,
          size.width * 0.22,
          size.height * 0.28,
        ),
        const Radius.circular(6),
      ),
      guide..color = Colors.white.withValues(alpha: 0.45),
    );
  }

  @override
  bool shouldRepaint(covariant _GuidePainter oldDelegate) =>
      oldDelegate.ready != ready;
}
