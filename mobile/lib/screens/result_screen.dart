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
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(20, 24, 20, 22),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: AppColors.line),
            ),
            child: Column(
              children: [
                Container(
                  width: 56,
                  height: 56,
                  decoration: const BoxDecoration(
                    color: AppColors.primarySoft,
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(Icons.check_rounded,
                      color: AppColors.ready, size: 32),
                ),
                const SizedBox(height: 14),
                Text(
                  result.displayCm,
                  style: const TextStyle(
                    fontSize: 48,
                    fontWeight: FontWeight.w900,
                    color: AppColors.ink,
                    letterSpacing: -1.5,
                  ),
                  textAlign: TextAlign.center,
                ),
                if (conf != null)
                  Text(
                    '${(conf * 100).round()}%',
                    style: const TextStyle(
                      color: AppColors.muted,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
              ],
            ),
          ),
          if (preview != null) ...[
            const SizedBox(height: 14),
            ClipRRect(
              borderRadius: BorderRadius.circular(20),
              child: Image.network(
                preview,
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => const SizedBox.shrink(),
              ),
            ),
          ],
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(child: _SizeCard(label: 'EU', value: '${result.eu}')),
              const SizedBox(width: 8),
              Expanded(
                  child: _SizeCard(label: 'US M', value: '${result.usMen}')),
              const SizedBox(width: 8),
              Expanded(
                  child: _SizeCard(label: 'US W', value: '${result.usWomen}')),
              const SizedBox(width: 8),
              Expanded(child: _SizeCard(label: 'UK', value: '${result.uk}')),
            ],
          ),
          const SizedBox(height: 22),
          FilledButton(
            onPressed: () {
              Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(
                  builder: (_) => MethodScreen(cameras: cameras),
                ),
                (_) => false,
              );
            },
            child: const Text('Again'),
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
      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 6),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.line),
      ),
      child: Column(
        children: [
          Text(value,
              style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w900,
                  color: AppColors.ink)),
          Text(label,
              style: const TextStyle(
                  color: AppColors.muted,
                  fontSize: 11,
                  fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}
