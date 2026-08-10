import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../models/measure_method.dart';
import '../theme/app_theme.dart';
import 'capture_screen.dart';

class GuidelinesScreen extends StatefulWidget {
  const GuidelinesScreen({
    super.key,
    required this.method,
    required this.cameras,
    required this.depthSupported,
  });

  final MeasureMethod method;
  final List<CameraDescription> cameras;
  final bool depthSupported;

  @override
  State<GuidelinesScreen> createState() => _GuidelinesScreenState();
}

class _GuidelinesScreenState extends State<GuidelinesScreen> {
  bool _acked = false;

  @override
  Widget build(BuildContext context) {
    final m = widget.method;
    return Scaffold(
      appBar: AppBar(
        title: Text(m.title),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: Image.asset(
              m.guideAsset,
              fit: BoxFit.fitWidth,
            ),
          ),
          const SizedBox(height: 16),
          const Text(
            'Do this',
            style: TextStyle(
              fontWeight: FontWeight.w800,
              fontSize: 16,
              color: AppColors.ready,
            ),
          ),
          const SizedBox(height: 8),
          ...m.dos.map((t) => _Bullet(text: t, ok: true)),
          const SizedBox(height: 14),
          const Text(
            'Avoid this',
            style: TextStyle(
              fontWeight: FontWeight.w800,
              fontSize: 16,
              color: AppColors.danger,
            ),
          ),
          const SizedBox(height: 8),
          ...m.donts.map((t) => _Bullet(text: t, ok: false)),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: AppColors.warnSoft,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: const Color(0xFFFDE68A)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Row(
                  children: [
                    Icon(Icons.lightbulb_outline, color: AppColors.wait),
                    SizedBox(width: 8),
                    Text(
                      'Quick checklist',
                      style: TextStyle(
                        fontWeight: FontWeight.w800,
                        color: AppColors.ink,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: m.checklist
                      .map(
                        (c) => Chip(
                          label: Text(c, style: const TextStyle(fontSize: 12)),
                          backgroundColor: Colors.white,
                          side: const BorderSide(color: AppColors.line),
                          visualDensity: VisualDensity.compact,
                        ),
                      )
                      .toList(),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          CheckboxListTile(
            value: _acked,
            onChanged: (v) => setState(() => _acked = v ?? false),
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            title: const Text(
              'I understand — bad photos will be blocked until Ready',
              style: TextStyle(fontSize: 14, color: AppColors.ink),
            ),
          ),
          const SizedBox(height: 8),
          FilledButton(
            onPressed: !_acked
                ? null
                : () {
                    Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => CaptureScreen(
                          cameras: widget.cameras,
                          method: m,
                          depthSupported: widget.depthSupported,
                        ),
                      ),
                    );
                  },
            child: const Text('Open camera'),
          ),
          const SizedBox(height: 8),
          const Text(
            'Capture stays locked until lighting, framing, and reference checks pass.',
            style: TextStyle(color: AppColors.muted, fontSize: 12, height: 1.35),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}

class _Bullet extends StatelessWidget {
  const _Bullet({required this.text, required this.ok});

  final String text;
  final bool ok;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            ok ? Icons.check_circle : Icons.cancel,
            size: 18,
            color: ok ? AppColors.ready : AppColors.danger,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(color: AppColors.ink, height: 1.35),
            ),
          ),
        ],
      ),
    );
  }
}
