import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../api/measure_api.dart';
import '../config.dart';
import '../theme/app_theme.dart';
import 'method_screen.dart';

class ResultScreen extends StatelessWidget {
  const ResultScreen({
    super.key,
    required this.result,
    required this.mode,
    required this.cameras,
    this.previewUrl,
  });

  final MeasureResult result;
  final String mode;
  final List<CameraDescription> cameras;
  final String? previewUrl;

  @override
  Widget build(BuildContext context) {
    final preview = previewUrl == null
        ? null
        : (previewUrl!.startsWith('http')
            ? previewUrl!
            : '$apiBaseUrl$previewUrl');
    final conf = result.confidence;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Result'),
        automaticallyImplyLeading: false,
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
        children: [
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: AppColors.line),
            ),
            child: Column(
              children: [
                const Icon(Icons.verified_rounded,
                    color: AppColors.ready, size: 36),
                const SizedBox(height: 8),
                const Text(
                  'Measurement complete',
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 18,
                    color: AppColors.ink,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  'Mode: $mode',
                  style: const TextStyle(color: AppColors.muted),
                ),
                if (conf != null) ...[
                  const SizedBox(height: 4),
                  Text(
                    'Confidence ${(conf * 100).round()}%',
                    style: const TextStyle(color: AppColors.muted, fontSize: 13),
                  ),
                ],
                const SizedBox(height: 18),
                Text(
                  result.displayCm,
                  style: const TextStyle(
                    fontSize: 40,
                    fontWeight: FontWeight.w900,
                    color: AppColors.ink,
                    letterSpacing: -1,
                  ),
                  textAlign: TextAlign.center,
                ),
                const Text(
                  'Foot length (nearest 0.5 cm)',
                  style: TextStyle(color: AppColors.muted),
                ),
              ],
            ),
          ),
          if (preview != null) ...[
            const SizedBox(height: 12),
            ClipRRect(
              borderRadius: BorderRadius.circular(16),
              child: Image.network(
                preview,
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => const SizedBox.shrink(),
              ),
            ),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: _SizeCard(label: 'EU', value: '${result.eu}')),
              const SizedBox(width: 8),
              Expanded(
                  child: _SizeCard(label: 'US Men', value: '${result.usMen}')),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                  child:
                      _SizeCard(label: 'US Women', value: '${result.usWomen}')),
              const SizedBox(width: 8),
              Expanded(child: _SizeCard(label: 'UK', value: '${result.uk}')),
            ],
          ),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppColors.warnSoft,
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Text(
              'Sizes are approximate conversions — not brand fitting advice. '
              'Re-measure if the ± range is large or confidence is low.',
              style: TextStyle(color: AppColors.ink, fontSize: 13, height: 1.35),
            ),
          ),
          const SizedBox(height: 18),
          FilledButton(
            onPressed: () {
              Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(
                  builder: (_) => MethodScreen(cameras: cameras),
                ),
                (_) => false,
              );
            },
            child: const Text('Measure again'),
          ),
        ],
      ),
    );
  }
}

class _SizeCard extends StatelessWidget {
  const _SizeCard({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(value,
              style: const TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.w800,
                  color: AppColors.ink)),
          Text(label, style: const TextStyle(color: AppColors.muted)),
        ],
      ),
    );
  }
}
