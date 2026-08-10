import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Top-down alignment guides for the live camera preview (per measure mode).
class GuideOverlayPainter extends CustomPainter {
  GuideOverlayPainter({
    required this.mode,
    required this.ready,
  });

  final String mode;
  final bool ready;

  @override
  void paint(Canvas canvas, Size size) {
    final accent = ready ? AppColors.ready : Colors.white;
    final frame = RRect.fromRectAndRadius(
      Rect.fromLTWH(12, 12, size.width - 24, size.height - 24),
      const Radius.circular(18),
    );

    // Soft vignette — keep focus in the working area.
    final vignette = Paint()
      ..shader = ui.Gradient.radial(
        Offset(size.width * 0.5, size.height * 0.48),
        size.shortestSide * 0.72,
        [
          Colors.transparent,
          Colors.black.withValues(alpha: 0.38),
        ],
        const [0.55, 1.0],
      );
    canvas.drawRect(Offset.zero & size, vignette);

    switch (mode) {
      case 'paper':
        _paintPaper(canvas, size, accent);
      case 'both':
        _paintBoth(canvas, size, accent);
      case 'depth':
        _paintDepth(canvas, size, accent);
      case 'card':
      default:
        _paintCard(canvas, size, accent);
    }

    final border = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = ready ? 3.2 : 2.4
      ..color = accent.withValues(alpha: ready ? 0.95 : 0.75);
    canvas.drawRRect(frame, border);
  }

  // —— layouts ——

  void _paintCard(Canvas canvas, Size size, Color accent) {
    final foot = _footSlot(
      center: Offset(size.width * 0.36, size.height * 0.52),
      length: size.height * 0.52,
      width: size.width * 0.28,
    );
    final card = _cardSlot(
      center: Offset(size.width * 0.72, size.height * 0.55),
      longSide: size.height * 0.28,
    );

    _dimOutside(canvas, size, Path()
      ..addOval(foot)
      ..addRRect(card));

    _dashedOval(canvas, foot, accent);
    _dashedRRect(canvas, card, accent);
    _heelToeMarks(canvas, foot, accent);
    _label(canvas, 'FOOT', Offset(foot.center.dx, foot.bottom + 14), accent);
    _label(canvas, 'CARD', Offset(card.center.dx, card.bottom + 14), accent);
  }

  void _paintPaper(Canvas canvas, Size size, Color accent) {
    final paper = _a4Slot(size);
    final foot = _footSlot(
      center: Offset(paper.center.dx, paper.center.dy + paper.height * 0.02),
      length: paper.height * 0.62,
      width: paper.width * 0.42,
    );

    _dimOutside(canvas, size, Path()..addRRect(paper));

    _dashedRRect(canvas, paper, accent);
    _cornerMarks(canvas, paper.outerRect, accent);
    _dashedOval(canvas, foot, accent.withValues(alpha: 0.9));
    _heelToeMarks(canvas, foot, accent);
    _label(canvas, 'A4', Offset(paper.center.dx, paper.top - 12), accent);
    _label(canvas, 'FOOT', Offset(foot.center.dx, foot.bottom + 12), accent);
  }

  void _paintBoth(Canvas canvas, Size size, Color accent) {
    final paper = _a4Slot(size);
    final foot = _footSlot(
      center: Offset(paper.center.dx - paper.width * 0.08, paper.center.dy),
      length: paper.height * 0.58,
      width: paper.width * 0.38,
    );
    final card = _cardSlot(
      center: Offset(paper.right - paper.width * 0.22, paper.center.dy + paper.height * 0.06),
      longSide: paper.height * 0.22,
    );

    _dimOutside(canvas, size, Path()..addRRect(paper));

    _dashedRRect(canvas, paper, accent);
    _cornerMarks(canvas, paper.outerRect, accent);
    _dashedOval(canvas, foot, accent);
    _heelToeMarks(canvas, foot, accent);
    _dashedRRect(canvas, card, accent);
    _label(canvas, 'A4', Offset(paper.center.dx, paper.top - 12), accent);
    _label(canvas, 'FOOT', Offset(foot.center.dx, foot.bottom + 12), accent);
    _label(canvas, 'CARD', Offset(card.center.dx, card.bottom + 12), accent);
  }

  void _paintDepth(Canvas canvas, Size size, Color accent) {
    final foot = _footSlot(
      center: Offset(size.width * 0.5, size.height * 0.52),
      length: size.height * 0.56,
      width: size.width * 0.36,
    );
    // Clear-floor ring — nudge user to keep clutter out.
    final clear = Rect.fromCenter(
      center: foot.center,
      width: foot.width * 1.55,
      height: foot.height * 1.28,
    );

    _dimOutside(canvas, size, Path()..addOval(clear));

    final ring = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.4
      ..color = accent.withValues(alpha: 0.35);
    canvas.drawOval(clear, ring);

    _dashedOval(canvas, foot, accent);
    _heelToeMarks(canvas, foot, accent);
    _crosshair(canvas, foot.center, accent.withValues(alpha: 0.45));
    _label(canvas, 'FOOT', Offset(foot.center.dx, foot.bottom + 14), accent);
    _label(
      canvas,
      'CLEAR FLOOR',
      Offset(foot.center.dx, clear.top - 12),
      accent.withValues(alpha: 0.85),
    );
  }

  // —— geometry helpers ——

  RRect _a4Slot(Size size) {
    // Portrait A4 ≈ 1 : 1.414 inside the preview with margin.
    final maxW = size.width * 0.78;
    final maxH = size.height * 0.72;
    var w = maxW;
    var h = w * 1.414;
    if (h > maxH) {
      h = maxH;
      w = h / 1.414;
    }
    final rect = Rect.fromCenter(
      center: Offset(size.width * 0.5, size.height * 0.48),
      width: w,
      height: h,
    );
    return RRect.fromRectAndRadius(rect, const Radius.circular(10));
  }

  Rect _footSlot({
    required Offset center,
    required double length,
    required double width,
  }) {
    // Top-down footprint: elongated oval (toes toward top of frame).
    return Rect.fromCenter(center: center, width: width, height: length);
  }

  RRect _cardSlot({required Offset center, required double longSide}) {
    // ISO/IEC 7810 ID-1 ≈ 85.6 × 53.98 → aspect ~1.586
    final h = longSide;
    final w = h / 1.586;
    return RRect.fromRectAndRadius(
      Rect.fromCenter(center: center, width: w, height: h),
      const Radius.circular(4),
    );
  }

  void _dimOutside(Canvas canvas, Size size, Path keepClear) {
    final full = Path()..addRect(Offset.zero & size);
    final cut = Path.combine(PathOperation.difference, full, keepClear);
    canvas.drawPath(
      cut,
      Paint()..color = Colors.black.withValues(alpha: 0.32),
    );
  }

  void _dashedOval(Canvas canvas, Rect oval, Color color) {
    final path = Path()..addOval(oval);
    _drawDashedPath(canvas, path, color, stroke: 2.4);
    // Soft halo so it reads on bright floors.
    canvas.drawOval(
      oval,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 5
        ..color = Colors.black.withValues(alpha: 0.22),
    );
    _drawDashedPath(canvas, path, color, stroke: 2.4);
  }

  void _dashedRRect(Canvas canvas, RRect rrect, Color color) {
    final path = Path()..addRRect(rrect);
    canvas.drawRRect(
      rrect,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 5
        ..color = Colors.black.withValues(alpha: 0.22),
    );
    _drawDashedPath(canvas, path, color, stroke: 2.4);
  }

  void _cornerMarks(Canvas canvas, Rect rect, Color color) {
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.square
      ..color = color.withValues(alpha: 0.95);
    const len = 18.0;
    final corners = [
      (rect.topLeft, 1.0, 1.0),
      (rect.topRight, -1.0, 1.0),
      (rect.bottomLeft, 1.0, -1.0),
      (rect.bottomRight, -1.0, -1.0),
    ];
    for (final (p, sx, sy) in corners) {
      canvas.drawLine(p, Offset(p.dx + len * sx, p.dy), paint);
      canvas.drawLine(p, Offset(p.dx, p.dy + len * sy), paint);
    }
  }

  void _heelToeMarks(Canvas canvas, Rect foot, Color color) {
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..color = color.withValues(alpha: 0.7);
    // Toe tip (top) + heel (bottom) ticks.
    final cx = foot.center.dx;
    canvas.drawLine(
      Offset(cx - 10, foot.top),
      Offset(cx + 10, foot.top),
      paint,
    );
    canvas.drawLine(
      Offset(cx - 14, foot.bottom),
      Offset(cx + 14, foot.bottom),
      paint,
    );
  }

  void _crosshair(Canvas canvas, Offset c, Color color) {
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2
      ..color = color;
    const arm = 10.0;
    canvas.drawLine(Offset(c.dx - arm, c.dy), Offset(c.dx + arm, c.dy), paint);
    canvas.drawLine(Offset(c.dx, c.dy - arm), Offset(c.dx, c.dy + arm), paint);
  }

  void _label(Canvas canvas, String text, Offset center, Color color) {
    final tp = TextPainter(
      text: TextSpan(
        text: text,
        style: TextStyle(
          color: color.withValues(alpha: 0.95),
          fontSize: 11,
          fontWeight: FontWeight.w800,
          letterSpacing: 1.1,
          shadows: const [
            Shadow(blurRadius: 6, color: Colors.black54),
          ],
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, Offset(center.dx - tp.width / 2, center.dy - tp.height / 2));
  }

  void _drawDashedPath(
    Canvas canvas,
    Path path,
    Color color, {
    double stroke = 2.2,
    double dash = 8,
    double gap = 5,
  }) {
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.round
      ..color = color.withValues(alpha: 0.92);

    for (final metric in path.computeMetrics()) {
      var dist = 0.0;
      var draw = true;
      while (dist < metric.length) {
        final len = draw ? dash : gap;
        final next = math.min(dist + len, metric.length);
        if (draw) {
          canvas.drawPath(metric.extractPath(dist, next), paint);
        }
        dist = next;
        draw = !draw;
      }
    }
  }

  @override
  bool shouldRepaint(covariant GuideOverlayPainter oldDelegate) =>
      oldDelegate.ready != ready || oldDelegate.mode != mode;
}
