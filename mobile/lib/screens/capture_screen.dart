import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';

import '../api/measure_api.dart';
import '../config.dart';
import '../models/measure_method.dart';
import '../services/depth_capture.dart';
import '../theme/app_theme.dart';
import '../utils/camera_jpeg.dart';
import '../widgets/guide_overlay.dart';
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
  bool _streaming = false;
  DateTime _lastValidate = DateTime.fromMillisecondsSinceEpoch(0);

  static const _readyHoldNeeded = 2;
  static const _validateInterval = Duration(milliseconds: 900);
  static const _burstCount = 3;

  String get _mode => widget.method.id;

  @override
  void initState() {
    super.initState();
    SystemChrome.setSystemUIOverlayStyle(SystemUiOverlayStyle.dark);
    if (_mode == 'depth' && !widget.depthSupported) {
      setState(() {
        _statusText = 'No LiDAR';
        _message =
            'This device cannot capture depth. Production mode is A4 paper.';
      });
    }
    _initCamera();
  }

  @override
  void dispose() {
    _stopStream();
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _releaseCameraForDepth() async {
    await _stopStream();
    final c = _controller;
    _controller = null;
    if (mounted) setState(() {});
    if (c != null) {
      try {
        await c.dispose();
      } catch (_) {}
    }
    await Future<void>.delayed(const Duration(milliseconds: 450));
  }

  Future<void> _stopStream() async {
    final c = _controller;
    if (c == null || !_streaming) return;
    try {
      await c.stopImageStream();
    } catch (_) {}
    _streaming = false;
  }

  Future<void> _initCamera({bool resumeAligning = false}) async {
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
      imageFormatGroup: ImageFormatGroup.yuv420,
    );
    try {
      await controller.initialize();
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() {
        _controller = controller;
        if (_mode == 'depth' && !widget.depthSupported) {
          _statusText = 'No LiDAR';
          _message = 'This device cannot capture depth.';
        } else if (resumeAligning) {
          _statusText = 'Aligning…';
          _message = 'Camera restored — re-check framing, then capture again.';
          _ready = false;
          _readyStreak = 0;
        } else {
          _statusText = 'Aligning…';
          _message = 'Follow the guide — capture unlocks when Ready.';
        }
      });
      if (!(_mode == 'depth' && !widget.depthSupported)) {
        await _startValidationStream();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _statusText = 'Camera error';
        _message = '$e';
      });
    }
  }

  Future<void> _startValidationStream() async {
    final c = _controller;
    if (c == null || !c.value.isInitialized || _streaming) return;
    try {
      await c.startImageStream(_onStreamFrame);
      _streaming = true;
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _statusText = 'Stream error';
        _message = 'Could not start preview validation: $e';
      });
    }
  }

  void _onStreamFrame(CameraImage image) {
    if (_busy || _processing || !mounted) return;
    final now = DateTime.now();
    if (now.difference(_lastValidate) < _validateInterval) return;
    _lastValidate = now;
    final jpeg = cameraImageToJpeg(image);
    if (jpeg == null) return;
    _busy = true;
    _api.validateFrame(jpeg, _mode).then((result) {
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
    }).catchError((e) {
      if (!mounted || _processing) return;
      setState(() {
        _ready = false;
        _readyStreak = 0;
        _statusText = 'Checking…';
        _message = 'API unreachable ($apiBaseUrl). Start the server first.';
      });
    }).whenComplete(() {
      _busy = false;
    });
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
          ? 'Releasing camera for depth…'
          : 'Capturing burst — measuring securely…';
    });

    try {
      late final String jobId;
      if (_mode == 'depth') {
        await _releaseCameraForDepth();
        if (!mounted) return;
        setState(() => _message = 'Capturing LiDAR depth…');
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
        // Pause stream so still capture cannot race takePicture.
        await _stopStream();
        final c = _controller!;
        final burst = <Uint8List>[];
        for (var i = 0; i < _burstCount; i++) {
          final file = await c.takePicture();
          final bytes = await file.readAsBytes();
          burst.add(Uint8List.fromList(bytes));
          try {
            await File(file.path).delete();
          } catch (_) {}
          if (i < _burstCount - 1) {
            await Future<void>.delayed(const Duration(milliseconds: 120));
          }
        }
        setState(() => _message = 'Measuring securely in the background…');
        jobId = await _api.createBurstJob(burst, _mode);
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
              previewUrl: job.previewUrl,
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
      if (_mode == 'depth' && _controller == null) {
        await _initCamera(resumeAligning: true);
      } else {
        await _startValidationStream();
      }
    } catch (e) {
      if (!mounted) return;
      final msg = e is PlatformException
          ? DepthCapture.friendlyMessage(e)
          : '$e';
      setState(() {
        _processing = false;
        _ready = false;
        _readyStreak = 0;
        _statusText = 'Failed';
        _message = msg;
      });
      if (_mode == 'depth' && _controller == null) {
        await _initCamera(resumeAligning: true);
      } else {
        await _startValidationStream();
      }
    }
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
                      child: Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const CircularProgressIndicator(
                              color: AppColors.primary,
                            ),
                            if (_processing && _mode == 'depth') ...[
                              const SizedBox(height: 12),
                              const Text(
                                'Depth sensor active…',
                                style: TextStyle(
                                  color: Colors.white70,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  IgnorePointer(
                    child: CustomPaint(
                      painter: GuideOverlayPainter(
                        mode: _mode,
                        ready: _ready,
                      ),
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
                ? 'Three photos will be taken and averaged for a stable result.'
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
            style: const TextStyle(
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
    'reference': 'Paper',
    'full_frame': 'Full frame',
    'content': 'Foot',
    'tilt': 'Tilt',
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
