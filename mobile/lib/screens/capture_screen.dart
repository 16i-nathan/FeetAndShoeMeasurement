import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';

import '../api/measure_api.dart';
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
  String _statusText = 'Starting…';
  String _message = 'Allow camera';
  Map<String, bool> _checks = const {};
  bool _busy = false;
  bool _processing = false;
  bool _streaming = false;
  /// Live depth availability (re-checked; not the stale home hint).
  late bool _depthOk;
  DateTime _lastValidate = DateTime.fromMillisecondsSinceEpoch(0);

  static const _readyHoldNeeded = 1;
  static const _validateInterval = Duration(milliseconds: 900);
  static const _burstCount = 3;

  String get _mode => widget.method.id;

  @override
  void initState() {
    super.initState();
    SystemChrome.setSystemUIOverlayStyle(SystemUiOverlayStyle.dark);
    _depthOk = widget.depthSupported || _mode != 'depth';
    if (_mode == 'depth' && !_depthOk) {
      setState(() {
        _statusText = 'No LiDAR';
        _message = 'Use A4 instead';
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
        _statusText = 'Blocked';
        _message = 'Enable camera';
      });
      return;
    }
    if (widget.cameras.isEmpty) {
      setState(() {
        _statusText = 'No camera';
        _message = 'Use a phone';
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
        if (_mode == 'depth' && !_depthOk) {
          _statusText = 'No LiDAR';
          _message = 'Use A4 instead';
        } else if (resumeAligning) {
          _statusText = 'Align…';
          _message = 'Frame again';
          _ready = false;
          _readyStreak = 0;
        } else {
          _statusText = 'Align…';
          _message = 'Match the guide';
        }
      });
      if (!(_mode == 'depth' && !_depthOk)) {
        await _startValidationStream();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _statusText = 'Error';
        _message = 'Camera failed';
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
        _statusText = 'Error';
        _message = 'Preview failed';
      });
    }
  }

  String _shortMsg(String raw) {
    final t = raw.trim();
    if (t.isEmpty) return 'Adjust';
    if (t.length <= 28) return t;
    // Prefer first clause before em-dash / period.
    final cut = t.split(RegExp(r'[—.–]| · ')).first.trim();
    if (cut.length <= 32) return cut;
    return '${cut.substring(0, 28).trim()}…';
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
            : (result.ready ? 'Hold…' : 'Adjust');
        _message = lockedIn ? 'Tap Capture' : _shortMsg(result.message);
        _checks = result.checks;
      });
    }).catchError((e) {
      if (!mounted || _processing) return;
      setState(() {
        _ready = false;
        _readyStreak = 0;
        _statusText = 'Offline';
        _message = 'Start API';
      });
    }).whenComplete(() {
      _busy = false;
    });
  }

  bool get _canCapture {
    if (_processing) return false;
    if (_mode == 'depth' && !_depthOk) return false;
    return _ready && (_controller?.value.isInitialized ?? false);
  }

  Future<void> _capture() async {
    if (!_canCapture) return;

    setState(() {
      _processing = true;
      _statusText = '…';
      _message = _mode == 'depth' ? 'Depth…' : 'Burst…';
    });

    try {
      late final String jobId;
      if (_mode == 'depth') {
        await _releaseCameraForDepth();
        if (!mounted) return;
        setState(() => _message = 'Waking…');
        try {
          await DepthCapture.warmUp();
        } catch (_) {}
        if (!mounted) return;
        setState(() => _message = 'Depth…');
        final frame = await DepthCapture.captureWithRetry(attempts: 3);
        if (!mounted) return;
        setState(() => _message = 'Measuring…');
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
        setState(() => _message = 'Measuring…');
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
        _statusText = 'Retry';
        _message = _shortMsg(
          job.error ?? job.message ?? 'Retake',
        );
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
          : 'Failed';
      setState(() {
        _processing = false;
        _ready = false;
        _readyStreak = 0;
        _statusText = 'Failed';
        _message = _shortMsg(msg);
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
    final title = _mode == 'paper'
        ? 'A4'
        : (_mode == 'depth' ? 'Depth' : widget.method.title);
    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        title: Text(title),
        actions: [
          IconButton(
            tooltip: 'Tips',
            onPressed: () => Navigator.of(context).pop(),
            icon: const Icon(Icons.lightbulb_outline_rounded),
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
                  if (!_ready || _processing)
                    Positioned(
                      left: 12,
                      right: 12,
                      bottom: 12,
                      child: Align(
                        alignment: Alignment.bottomCenter,
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 14,
                            vertical: 8,
                          ),
                          decoration: BoxDecoration(
                            color: Colors.white.withValues(alpha: 0.92),
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Text(
                            _message,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              color: AppColors.ink,
                              fontWeight: FontWeight.w700,
                              fontSize: 13,
                            ),
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
          const SizedBox(height: 14),
          FilledButton(
            onPressed: _canCapture && !_processing ? _capture : null,
            child: Text(
              _processing ? '…' : (_canCapture ? 'Capture' : 'Wait'),
            ),
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
    'reference': 'Reference',
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
