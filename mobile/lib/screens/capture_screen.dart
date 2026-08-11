import 'dart:async';
import 'dart:io';

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

enum _Phase { live, reviewing, measuring, failed }

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
  String _hint = 'Match the guide';
  Map<String, bool> _checks = const {};
  bool _busy = false;
  bool _streaming = false;
  late bool _depthOk;

  _Phase _phase = _Phase.live;
  Uint8List? _frozenJpeg;
  Uint8List? _lastReadyJpeg;
  String? _failMessage;
  int _session = 0;

  DateTime _lastValidate = DateTime.fromMillisecondsSinceEpoch(0);

  static const _readyHoldNeeded = 2;
  static const _validateInterval = Duration(milliseconds: 850);
  static const _burstCount = 3;

  String get _mode => widget.method.id;
  bool get _isLive => _phase == _Phase.live;

  @override
  void initState() {
    super.initState();
    SystemChrome.setSystemUIOverlayStyle(SystemUiOverlayStyle.light);
    _depthOk = widget.depthSupported || _mode != 'depth';
    if (_mode == 'depth' && !_depthOk) {
      _statusText = 'No LiDAR';
      _hint = 'Use A4 instead';
    }
    _initCamera();
  }

  @override
  void dispose() {
    _session++;
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

  Future<void> _initCamera() async {
    final cam = await Permission.camera.request();
    if (!cam.isGranted) {
      setState(() {
        _statusText = 'Blocked';
        _hint = 'Enable camera';
      });
      return;
    }
    if (widget.cameras.isEmpty) {
      setState(() {
        _statusText = 'No camera';
        _hint = 'Use a phone';
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
        _phase = _Phase.live;
        _frozenJpeg = null;
        _failMessage = null;
        _ready = false;
        _readyStreak = 0;
        _checks = const {};
        if (_mode == 'depth' && !_depthOk) {
          _statusText = 'No LiDAR';
          _hint = 'Use A4 instead';
        } else {
          _statusText = 'Align';
          _hint = 'Match the guide';
        }
      });
      if (!(_mode == 'depth' && !_depthOk)) {
        await _startValidationStream();
      }
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _statusText = 'Error';
        _hint = 'Camera failed';
      });
    }
  }

  Future<void> _startValidationStream() async {
    final c = _controller;
    if (c == null || !c.value.isInitialized || _streaming) return;
    try {
      await c.startImageStream(_onStreamFrame);
      _streaming = true;
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _statusText = 'Error';
        _hint = 'Preview failed';
      });
    }
  }

  String _shortMsg(String raw) {
    final t = raw.trim();
    if (t.isEmpty) return 'Adjust';
    if (t.length <= 36) return t;
    final cut = t.split(RegExp(r'[—.–]| · ')).first.trim();
    if (cut.length <= 40) return cut;
    return '${cut.substring(0, 36).trim()}…';
  }

  void _onStreamFrame(CameraImage image) {
    if (!_isLive || _busy || !mounted) return;
    final now = DateTime.now();
    if (now.difference(_lastValidate) < _validateInterval) return;
    _lastValidate = now;
    final jpeg = cameraImageToJpeg(image);
    if (jpeg == null) return;
    final session = _session;
    _busy = true;
    _api.validateFrame(jpeg, _mode).then((result) {
      if (!mounted || session != _session || !_isLive) return;
      final streak = result.ready ? _readyStreak + 1 : 0;
      final lockedIn = streak >= _readyHoldNeeded;
      setState(() {
        _readyStreak = streak;
        _ready = lockedIn;
        _checks = result.checks;
        if (lockedIn) {
          _lastReadyJpeg = jpeg;
          _statusText = 'Ready';
          _hint = 'Tap shutter';
        } else {
          _statusText = result.ready ? 'Hold…' : 'Adjust';
          _hint = _shortMsg(result.message);
        }
      });
    }).catchError((_) {
      if (!mounted || session != _session || !_isLive) return;
      setState(() {
        _ready = false;
        _readyStreak = 0;
        _checks = const {};
        _statusText = 'Offline';
        _hint = 'API offline';
      });
    }).whenComplete(() {
      if (session == _session) _busy = false;
    });
  }

  bool get _canShutter {
    if (!_isLive) return false;
    if (_mode == 'depth' && !_depthOk) return false;
    return _ready && (_controller?.value.isInitialized ?? false);
  }

  Future<void> _onShutter() async {
    if (!_canShutter) return;

    final session = ++_session;
    setState(() {
      _phase = _Phase.reviewing;
      _statusText = 'Captured';
      _hint = 'Measuring…';
      _failMessage = null;
      _ready = false;
      _checks = const {};
      // Freeze last good preview immediately so UI never flips back to live tips.
      _frozenJpeg = _lastReadyJpeg;
    });

    try {
      await _stopStream();
      if (!mounted || session != _session) return;

      late final String jobId;
      if (_mode == 'depth') {
        await _releaseCameraForDepth();
        if (!mounted || session != _session) return;
        setState(() {
          _phase = _Phase.measuring;
          _hint = 'Waking AR…';
        });
        try {
          await DepthCapture.warmUp();
        } catch (_) {}
        if (!mounted || session != _session) return;
        setState(() => _hint = 'Depth…');
        final frame = await DepthCapture.captureWithRetry(attempts: 3);
        if (!mounted || session != _session) return;
        setState(() {
          _frozenJpeg = frame.jpegBytes;
          _hint = 'Measuring…';
        });
        jobId = await _api.createJob(
          frame.jpegBytes,
          'depth',
          depthNpy: frame.depthNpyBytes,
          fx: frame.fx,
          fy: frame.fy,
          cx: frame.cx,
          cy: frame.cy,
        );
      } else if (_mode == 'gemini' || _mode == 'compare') {
        // Single still — AI / compare (no burst).
        final c = _controller!;
        final file = await c.takePicture();
        final bytes = Uint8List.fromList(await file.readAsBytes());
        try {
          await File(file.path).delete();
        } catch (_) {}
        if (!mounted || session != _session) return;
        setState(() {
          _frozenJpeg = bytes;
          _phase = _Phase.measuring;
          _hint = _mode == 'compare' ? 'Comparing…' : 'AI measuring…';
        });
        jobId = await _api.createJob(bytes, _mode);
      } else {
        final c = _controller!;
        final burst = <Uint8List>[];
        if (_lastReadyJpeg != null) {
          burst.add(_lastReadyJpeg!);
        }
        for (var i = 0; i < _burstCount; i++) {
          final file = await c.takePicture();
          final bytes = Uint8List.fromList(await file.readAsBytes());
          burst.add(bytes);
          try {
            await File(file.path).delete();
          } catch (_) {}
          if (i == 0 && mounted && session == _session) {
            setState(() {
              _frozenJpeg = bytes;
              _phase = _Phase.measuring;
              _hint = 'Measuring…';
            });
          }
          if (i < _burstCount - 1) {
            await Future<void>.delayed(const Duration(milliseconds: 100));
          }
        }
        if (!mounted || session != _session) return;
        setState(() {
          _phase = _Phase.measuring;
          _hint = 'Measuring…';
          _frozenJpeg ??= burst.isNotEmpty ? burst.last : null;
        });
        // Prefer still frames; keep ready preview as first sample for stability.
        jobId = await _api.createBurstJob(burst, _mode);
      }

      final job = await _api.waitForJob(
        jobId,
        timeout: Duration(
          seconds: (_mode == 'gemini' || _mode == 'compare') ? 120 : 120,
        ),
      );
      if (!mounted || session != _session) return;

      if (job.status == 'done' && job.result != null) {
        await Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => ResultScreen(
              result: job.result!,
              mode: job.mode,
              cameras: widget.cameras,
              previewUrl: job.previewUrl,
              jobId: job.id,
            ),
          ),
        );
        return;
      }

      setState(() {
        _phase = _Phase.failed;
        _statusText = 'Retry';
        _failMessage = _shortMsg(job.error ?? job.message ?? 'Retake');
        _hint = _failMessage!;
      });
    } catch (e) {
      if (!mounted || session != _session) return;
      final msg = e is PlatformException
          ? DepthCapture.friendlyMessage(e)
          : 'Failed';
      setState(() {
        _phase = _Phase.failed;
        _statusText = 'Failed';
        _failMessage = _shortMsg(msg);
        _hint = _failMessage!;
      });
    }
  }

  Future<void> _retake() async {
    _session++;
    setState(() {
      _phase = _Phase.live;
      _frozenJpeg = null;
      _lastReadyJpeg = null;
      _failMessage = null;
      _ready = false;
      _readyStreak = 0;
      _checks = const {};
      _statusText = 'Align';
      _hint = 'Match the guide';
    });

    if (_mode == 'depth' && _controller == null) {
      await _initCamera();
      return;
    }
    await _startValidationStream();
  }

  @override
  Widget build(BuildContext context) {
    final c = _controller;
    final title = _mode == 'paper'
        ? 'A4'
        : (_mode == 'depth' ? 'Depth' : widget.method.title);

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          // —— viewfinder / frozen capture ——
          if (_frozenJpeg != null && !_isLive)
            FittedBox(
              fit: BoxFit.cover,
              child: SizedBox(
                width: MediaQuery.sizeOf(context).width,
                height: MediaQuery.sizeOf(context).height,
                child: Image.memory(_frozenJpeg!, fit: BoxFit.cover),
              ),
            )
          else if (c != null && c.value.isInitialized)
            FittedBox(
              fit: BoxFit.cover,
              child: SizedBox(
                width: c.value.previewSize?.height ??
                    MediaQuery.sizeOf(context).width,
                height: c.value.previewSize?.width ??
                    MediaQuery.sizeOf(context).height,
                child: CameraPreview(c),
              ),
            )
          else
            const ColoredBox(
              color: Colors.black,
              child: Center(
                child: CircularProgressIndicator(color: Colors.white70),
              ),
            ),

          // Guides only while live
          if (_isLive)
            IgnorePointer(
              child: CustomPaint(
                painter: GuideOverlayPainter(mode: _mode, ready: _ready),
                child: const SizedBox.expand(),
              ),
            ),

          // Dim while measuring
          if (_phase == _Phase.measuring || _phase == _Phase.reviewing)
            ColoredBox(color: Colors.black.withValues(alpha: 0.35)),

          // Top bar
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 4, 8, 0),
              child: Row(
                children: [
                  IconButton(
                    onPressed: () => Navigator.of(context).maybePop(),
                    icon: const Icon(Icons.close_rounded, color: Colors.white),
                  ),
                  Expanded(
                    child: Text(
                      title,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w800,
                        fontSize: 16,
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: () => Navigator.of(context).maybePop(),
                    icon: const Icon(Icons.lightbulb_outline_rounded,
                        color: Colors.white70),
                  ),
                ],
              ),
            ),
          ),

          // Status pill
          SafeArea(
            child: Align(
              alignment: Alignment.topCenter,
              child: Padding(
                padding: const EdgeInsets.only(top: 56),
                child: _StatusPill(
                  ready: _ready && _isLive,
                  text: _statusText,
                  measuring: _phase == _Phase.measuring ||
                      _phase == _Phase.reviewing,
                ),
              ),
            ),
          ),

          // Bottom controls
          SafeArea(
            child: Align(
              alignment: Alignment.bottomCenter,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (_isLive && _hint.isNotEmpty && !_ready)
                      Container(
                        margin: const EdgeInsets.only(bottom: 14),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 14,
                          vertical: 8,
                        ),
                        decoration: BoxDecoration(
                          color: Colors.black.withValues(alpha: 0.55),
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Text(
                          _hint,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w600,
                            fontSize: 13,
                          ),
                        ),
                      ),
                    if (_phase == _Phase.failed) ...[
                      Container(
                        width: double.infinity,
                        margin: const EdgeInsets.only(bottom: 14),
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: Colors.black.withValues(alpha: 0.7),
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Text(
                          _failMessage ?? 'Retake',
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                          onPressed: _retake,
                          style: FilledButton.styleFrom(
                            backgroundColor: Colors.white,
                            foregroundColor: Colors.black,
                          ),
                          child: const Text('Retake'),
                        ),
                      ),
                    ] else if (_phase == _Phase.measuring ||
                        _phase == _Phase.reviewing) ...[
                      const SizedBox(
                        width: 28,
                        height: 28,
                        child: CircularProgressIndicator(
                          strokeWidth: 3,
                          color: Colors.white,
                        ),
                      ),
                      const SizedBox(height: 10),
                      Text(
                        _hint,
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ] else ...[
                      // Compact live checks (icons only when failing)
                      _LiveDots(checks: _checks),
                      const SizedBox(height: 16),
                      _ShutterButton(
                        enabled: _canShutter,
                        onTap: _onShutter,
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({
    required this.ready,
    required this.text,
    required this.measuring,
  });

  final bool ready;
  final String text;
  final bool measuring;

  @override
  Widget build(BuildContext context) {
    final color = measuring
        ? AppColors.primary
        : (ready ? AppColors.ready : AppColors.wait);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.7)),
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
              fontWeight: FontWeight.w800,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }
}

class _ShutterButton extends StatelessWidget {
  const _ShutterButton({required this.enabled, required this.onTap});

  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: enabled ? onTap : null,
      child: AnimatedOpacity(
        duration: const Duration(milliseconds: 160),
        opacity: enabled ? 1 : 0.45,
        child: Container(
          width: 74,
          height: 74,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(color: Colors.white, width: 4),
          ),
          padding: const EdgeInsets.all(5),
          child: DecoratedBox(
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: enabled ? Colors.white : Colors.white54,
            ),
          ),
        ),
      ),
    );
  }
}

class _LiveDots extends StatelessWidget {
  const _LiveDots({required this.checks});

  final Map<String, bool> checks;

  static const _keys = [
    'brightness',
    'sharpness',
    'no_glare',
    'reference',
    'full_frame',
    'content',
    'tilt',
  ];

  @override
  Widget build(BuildContext context) {
    final present = _keys.where((k) => checks.containsKey(k)).toList();
    if (present.isEmpty) return const SizedBox.shrink();
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        for (final k in present)
          Container(
            width: 8,
            height: 8,
            margin: const EdgeInsets.symmetric(horizontal: 3),
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: checks[k] == true
                  ? AppColors.ready
                  : Colors.white.withValues(alpha: 0.35),
            ),
          ),
      ],
    );
  }
}
