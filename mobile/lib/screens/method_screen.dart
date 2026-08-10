import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../config.dart';
import '../models/measure_method.dart';
import '../services/depth_capture.dart';
import '../theme/app_theme.dart';
import 'guidelines_screen.dart';

class MethodScreen extends StatefulWidget {
  const MethodScreen({super.key, required this.cameras});

  final List<CameraDescription> cameras;

  @override
  State<MethodScreen> createState() => _MethodScreenState();
}

class _MethodScreenState extends State<MethodScreen> {
  String? _selected;
  bool _depthSupported = false;
  bool _checkingDepth = true;

  List<MeasureMethod> get _methods => methodsForBuild(labModes: labModes);

  @override
  void initState() {
    super.initState();
    _selected = paperMethod.id;
    _loadDepth();
    // Production: skip picker when only A4 is available.
    if (!labModes) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        _openGuidelines(paperMethod);
      });
    }
  }

  Future<void> _loadDepth() async {
    final ok = await DepthCapture.isSupported();
    if (!mounted) return;
    setState(() {
      _depthSupported = ok;
      _checkingDepth = false;
    });
  }

  void _openGuidelines(MeasureMethod method) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => GuidelinesScreen(
          method: method,
          cameras: widget.cameras,
          depthSupported: _depthSupported,
        ),
      ),
    );
  }

  IconData _icon(String key) {
    switch (key) {
      case 'credit_card':
        return Icons.credit_card_rounded;
      case 'description':
        return Icons.description_outlined;
      case 'layers':
        return Icons.layers_outlined;
      case 'view_in_ar':
        return Icons.view_in_ar_outlined;
      default:
        return Icons.straighten;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!labModes) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }

    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 28),
          children: [
            Text(
              'Foot Measure',
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                    color: AppColors.ink,
                    letterSpacing: -0.6,
                  ),
            ),
            const SizedBox(height: 6),
            const Text(
              'Lab modes enabled. Production builds use A4 paper only.',
              style: TextStyle(color: AppColors.muted, height: 1.4),
            ),
            const SizedBox(height: 20),
            ..._methods.map((m) {
              final selected = _selected == m.id;
              final disabled =
                  m.needsDepthHardware && !_depthSupported && !_checkingDepth;
              return Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Material(
                  color: AppColors.surface,
                  borderRadius: BorderRadius.circular(16),
                  child: InkWell(
                    borderRadius: BorderRadius.circular(16),
                    onTap: disabled
                        ? null
                        : () => setState(() => _selected = m.id),
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 180),
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(16),
                        border: Border.all(
                          color: selected
                              ? AppColors.primary
                              : AppColors.line,
                          width: selected ? 2 : 1,
                        ),
                        color: disabled
                            ? AppColors.bg
                            : (selected
                                ? AppColors.primarySoft.withValues(alpha: 0.35)
                                : AppColors.surface),
                      ),
                      child: Row(
                        children: [
                          Container(
                            width: 48,
                            height: 48,
                            decoration: BoxDecoration(
                              color: AppColors.bg,
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Icon(
                              _icon(m.icon),
                              color: disabled
                                  ? AppColors.muted
                                  : AppColors.primary,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  m.title,
                                  style: TextStyle(
                                    fontWeight: FontWeight.w700,
                                    fontSize: 16,
                                    color: disabled
                                        ? AppColors.muted
                                        : AppColors.ink,
                                  ),
                                ),
                                const SizedBox(height: 2),
                                Text(
                                  disabled
                                      ? 'Not available on this device (no LiDAR/AR depth)'
                                      : m.subtitle,
                                  style: const TextStyle(
                                    color: AppColors.muted,
                                    fontSize: 13,
                                    height: 1.3,
                                  ),
                                ),
                              ],
                            ),
                          ),
                          Icon(
                            selected
                                ? Icons.check_circle_rounded
                                : Icons.circle_outlined,
                            color: selected
                                ? AppColors.primary
                                : AppColors.line,
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              );
            }),
            const SizedBox(height: 8),
            FilledButton(
              onPressed: _selected == null
                  ? null
                  : () => _openGuidelines(methodById(_selected!)),
              child: const Text('Continue to guidelines'),
            ),
          ],
        ),
      ),
    );
  }
}
