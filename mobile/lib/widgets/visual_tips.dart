import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Compact icon tip used on guidelines / home.
class IconTip extends StatelessWidget {
  const IconTip({
    super.key,
    required this.icon,
    required this.label,
    this.ok = true,
  });

  final IconData icon;
  final String label;
  final bool ok;

  @override
  Widget build(BuildContext context) {
    final color = ok ? AppColors.primary : AppColors.danger;
    return Column(
      children: [
        Container(
          width: 64,
          height: 64,
          decoration: BoxDecoration(
            color: ok ? AppColors.primarySoft : AppColors.dangerSoft,
            borderRadius: BorderRadius.circular(18),
          ),
          child: Icon(icon, size: 30, color: color),
        ),
        const SizedBox(height: 8),
        Text(
          label,
          textAlign: TextAlign.center,
          style: TextStyle(
            fontWeight: FontWeight.w700,
            fontSize: 12,
            color: AppColors.ink.withValues(alpha: 0.85),
          ),
        ),
      ],
    );
  }
}

class TipGrid extends StatelessWidget {
  const TipGrid({super.key, required this.tips});

  final List<(IconData, String)> tips;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 16,
      runSpacing: 16,
      alignment: WrapAlignment.center,
      children: [
        for (final t in tips)
          SizedBox(
            width: 88,
            child: IconTip(icon: t.$1, label: t.$2),
          ),
      ],
    );
  }
}

/// Simple diagram: phone over foot / paper.
class SetupHeroGraphic extends StatelessWidget {
  const SetupHeroGraphic({super.key, required this.mode});

  final String mode; // paper | depth

  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: 1.15,
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(24),
          gradient: const LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFFE0F2F1), Color(0xFFF7F8FA)],
          ),
          border: Border.all(color: AppColors.line),
        ),
        child: CustomPaint(
          painter: _SetupPainter(isDepth: mode == 'depth'),
          child: const SizedBox.expand(),
        ),
      ),
    );
  }
}

class _SetupPainter extends CustomPainter {
  _SetupPainter({required this.isDepth});

  final bool isDepth;

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width * 0.5;
    final cy = size.height * 0.55;

    // Floor band
    final floor = Paint()..color = const Color(0xFFD1D5DB);
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(size.width * 0.08, size.height * 0.62, size.width * 0.84, size.height * 0.22),
        const Radius.circular(12),
      ),
      floor,
    );

    if (!isDepth) {
      // Paper
      final paper = Paint()..color = Colors.white;
      final paperRect = RRect.fromRectAndRadius(
        Rect.fromCenter(
          center: Offset(cx, cy + 8),
          width: size.width * 0.42,
          height: size.height * 0.38,
        ),
        const Radius.circular(6),
      );
      canvas.drawRRect(paperRect, paper);
      canvas.drawRRect(
        paperRect,
        Paint()
          ..color = AppColors.primary.withValues(alpha: 0.35)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2,
      );
    }

    // Foot oval
    final foot = Paint()..color = const Color(0xFF78716C);
    canvas.drawOval(
      Rect.fromCenter(
        center: Offset(cx, cy + (isDepth ? 4 : 4)),
        width: size.width * 0.16,
        height: size.height * 0.28,
      ),
      foot,
    );

    // Phone above
    final phone = RRect.fromRectAndRadius(
      Rect.fromCenter(
        center: Offset(cx, size.height * 0.22),
        width: size.width * 0.22,
        height: size.height * 0.28,
      ),
      const Radius.circular(10),
    );
    canvas.drawRRect(phone, Paint()..color = AppColors.ink);
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromCenter(
          center: Offset(cx, size.height * 0.21),
          width: size.width * 0.16,
          height: size.height * 0.18,
        ),
        const Radius.circular(4),
      ),
      Paint()..color = const Color(0xFF99F6E4),
    );

    // Rays / top-down hint
    final ray = Paint()
      ..color = AppColors.primary.withValues(alpha: 0.25)
      ..strokeWidth = 2;
    canvas.drawLine(Offset(cx, size.height * 0.34), Offset(cx - size.width * 0.12, cy - 20), ray);
    canvas.drawLine(Offset(cx, size.height * 0.34), Offset(cx + size.width * 0.12, cy - 20), ray);

    if (isDepth) {
      // Depth waves
      final wave = Paint()
        ..color = AppColors.primary.withValues(alpha: 0.4)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2;
      canvas.drawCircle(Offset(cx, cy), size.width * 0.18, wave);
      canvas.drawCircle(Offset(cx, cy), size.width * 0.26, wave);
    }
  }

  @override
  bool shouldRepaint(covariant _SetupPainter oldDelegate) =>
      oldDelegate.isDepth != isDepth;
}
