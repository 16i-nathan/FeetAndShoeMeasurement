import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
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
  /// Soft hint only — Depth is never disabled here.
  bool _depthHint = true;

  List<MeasureMethod> get _methods => methodsForBuild(labModes: labModes);

  @override
  void initState() {
    super.initState();
    _selected = paperMethod.id;
    _probeDepthHint();
  }

  Future<void> _probeDepthHint() async {
    if (kIsWeb) {
      if (!mounted) return;
      setState(() => _depthHint = false);
      return;
    }
    final ok = await DepthCapture.isSupported();
    if (!mounted) return;
    setState(() => _depthHint = ok);
  }

  void _open(MeasureMethod method) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => GuidelinesScreen(
          method: method,
          cameras: widget.cameras,
          // Hint only; Camera press re-checks + warms AR.
          depthSupported: method.id != 'depth' || _depthHint,
        ),
      ),
    );
  }

  IconData _icon(String key) {
    switch (key) {
      case 'credit_card':
        return Icons.credit_card_rounded;
      case 'description':
        return Icons.description_rounded;
      case 'layers':
        return Icons.layers_rounded;
      case 'view_in_ar':
        return Icons.view_in_ar_rounded;
      default:
        return Icons.straighten;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 28, 20, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Foot Measure',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                      fontWeight: FontWeight.w900,
                      color: AppColors.ink,
                      letterSpacing: -0.8,
                    ),
              ),
              const SizedBox(height: 6),
              const Text(
                'Pick a way',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.muted, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 28),
              Expanded(
                child: ListView(
                  children: [
                    for (final m in _methods) ...[
                      _ModeCard(
                        title: m.id == 'paper'
                            ? 'A4'
                            : (m.id == 'depth' ? 'Depth' : m.title),
                        subtitle: m.id == 'paper'
                            ? 'Any phone'
                            : (m.id == 'depth' ? 'LiDAR / AR' : m.subtitle),
                        icon: _icon(m.icon),
                        selected: _selected == m.id,
                        onTap: () => setState(() => _selected = m.id),
                      ),
                      const SizedBox(height: 12),
                    ],
                  ],
                ),
              ),
              FilledButton(
                onPressed: _selected == null
                    ? null
                    : () => _open(methodById(_selected!)),
                child: const Text('Next'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ModeCard extends StatelessWidget {
  const _ModeCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(22),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 20),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(22),
            border: Border.all(
              color: selected ? AppColors.primary : AppColors.line,
              width: selected ? 2.5 : 1,
            ),
            color: selected
                ? AppColors.primarySoft.withValues(alpha: 0.45)
                : AppColors.surface,
          ),
          child: Row(
            children: [
              Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(
                  color: AppColors.primarySoft,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Icon(icon, size: 36, color: AppColors.primary),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w900,
                        color: AppColors.ink,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      style: const TextStyle(
                        color: AppColors.muted,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
              Icon(
                selected ? Icons.check_circle_rounded : Icons.circle_outlined,
                color: selected ? AppColors.primary : AppColors.line,
                size: 28,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
