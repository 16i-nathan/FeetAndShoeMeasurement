import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../models/measure_method.dart';
import '../services/depth_capture.dart';
import '../theme/app_theme.dart';
import '../widgets/visual_tips.dart';
import 'capture_screen.dart';
import 'upload_screen.dart';

class GuidelinesScreen extends StatefulWidget {
  const GuidelinesScreen({
    super.key,
    required this.method,
    required this.cameras,
    required this.depthSupported,
  });

  final MeasureMethod method;
  final List<CameraDescription> cameras;
  /// Home-screen hint only — re-checked when opening Camera for Depth.
  final bool depthSupported;

  @override
  State<GuidelinesScreen> createState() => _GuidelinesScreenState();
}

class _GuidelinesScreenState extends State<GuidelinesScreen> {
  bool _waking = false;
  String? _depthNote;

  Future<void> _openCamera() async {
    final m = widget.method;
    if (m.id != 'depth') {
      _pushCapture(depthOk: true);
      return;
    }

    setState(() {
      _waking = true;
      _depthNote = null;
    });

    try {
      final ok = await DepthCapture.prepareForCapture();
      if (!mounted) return;
      if (!ok) {
        setState(() {
          _waking = false;
          _depthNote = 'No LiDAR on this device';
        });
        return;
      }
      setState(() => _waking = false);
      _pushCapture(depthOk: true);
    } catch (_) {
      if (!mounted) return;
      // Soft: still open capture and let retry path try.
      setState(() {
        _waking = false;
        _depthNote = 'AR waking — try Capture';
      });
      _pushCapture(depthOk: true);
    }
  }

  void _pushCapture({required bool depthOk}) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => CaptureScreen(
          cameras: widget.cameras,
          method: widget.method,
          depthSupported: depthOk,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final m = widget.method;
    return Scaffold(
      appBar: AppBar(
        title: Text(
          m.id == 'paper' ? 'A4' : (m.id == 'depth' ? 'Depth' : m.title),
        ),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
          child: Column(
            children: [
              Expanded(
                child: Center(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(16),
                    child: Image.asset(
                      m.guideAsset,
                      fit: BoxFit.contain,
                      errorBuilder: (_, __, ___) => SetupHeroGraphic(
                        mode: m.id == 'depth' ? 'depth' : 'paper',
                      ),
                    ),
                  ),
                ),
              ),
              if (_depthNote != null) ...[
                const SizedBox(height: 8),
                Container(
                  width: double.infinity,
                  padding:
                      const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
                  decoration: BoxDecoration(
                    color: AppColors.dangerSoft,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    _depthNote!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      color: AppColors.ink,
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: _waking ? null : _openCamera,
                icon: _waking
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.photo_camera_rounded),
                label: Text(_waking ? 'Waking AR…' : 'Camera'),
              ),
              if (m.id != 'depth') ...[
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: _waking
                      ? null
                      : () {
                          Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => UploadMeasureScreen(
                                cameras: widget.cameras,
                                method: m,
                              ),
                            ),
                          );
                        },
                  icon: const Icon(Icons.image_outlined),
                  label: const Text('Gallery'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
