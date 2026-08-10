import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../api/measure_api.dart';
import '../theme/app_theme.dart';
import 'method_screen.dart';

class ResultScreen extends StatelessWidget {
  const ResultScreen({
    super.key,
    required this.result,
    required this.mode,
    required this.cameras,
  });

  final MeasureResult result;
  final String mode;
  final List<CameraDescription> cameras;

  @override
  Widget build(BuildContext context) {
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
                const SizedBox(height: 18),
                Text(
                  '${result.cm} cm',
                  style: const TextStyle(
                    fontSize: 44,
                    fontWeight: FontWeight.w900,
                    color: AppColors.ink,
                    letterSpacing: -1,
                  ),
                ),
                const Text(
                  'Foot length',
                  style: TextStyle(color: AppColors.muted),
                ),
              ],
            ),
          ),
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
              'Sizes are approximate conversions for testing — not brand fitting advice.',
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
