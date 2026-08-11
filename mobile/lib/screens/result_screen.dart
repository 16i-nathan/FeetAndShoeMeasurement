import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/measure_api.dart';
import '../config.dart';
import '../theme/app_theme.dart';
import 'method_screen.dart';

class ResultScreen extends StatefulWidget {
  const ResultScreen({
    super.key,
    required this.result,
    required this.mode,
    required this.cameras,
    this.previewUrl,
    this.jobId,
  });

  final MeasureResult result;
  final String mode;
  final List<CameraDescription> cameras;
  final String? previewUrl;
  final String? jobId;

  @override
  State<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends State<ResultScreen> {
  late MeasureResult _result;
  final _truthCtrl = TextEditingController();
  final _api = MeasureApi();
  bool _saving = false;
  String? _truthMsg;
  String? _winner;

  @override
  void initState() {
    super.initState();
    _result = widget.result;
    final existing = _result.compare?.truthCm;
    if (existing != null) {
      _truthCtrl.text = existing.toStringAsFixed(1);
    }
  }

  @override
  void dispose() {
    _truthCtrl.dispose();
    super.dispose();
  }

  Future<void> _submitTruth() async {
    final id = widget.jobId;
    if (id == null || _saving) return;
    final raw = _truthCtrl.text.trim().replaceAll(',', '.');
    final truth = double.tryParse(raw);
    if (truth == null) {
      setState(() => _truthMsg = 'Enter a number in cm');
      return;
    }
    setState(() {
      _saving = true;
      _truthMsg = null;
    });
    try {
      final out = await _api.submitTruth(id, truth);
      if (!mounted) return;
      setState(() {
        _saving = false;
        _winner = out.winner;
        if (out.result != null) _result = out.result!;
        _truthMsg = out.winner == null
            ? 'Saved'
            : 'Saved · winner: ${out.winner}';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _truthMsg = 'Could not save truth';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final preview = widget.previewUrl == null
        ? null
        : (widget.previewUrl!.startsWith('http')
            ? widget.previewUrl!
            : '$apiBaseUrl${widget.previewUrl}');
    final conf = _result.confidence;
    final compare = _result.compare;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.mode == 'compare' ? 'Compare' : 'Result'),
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
                  _result.displayCm,
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
                    '${(conf * 100).round()}%'
                    '${_result.backend != null ? ' · ${_result.backend}' : ''}',
                    style: const TextStyle(
                      color: AppColors.muted,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
              ],
            ),
          ),
          if (compare != null) ...[
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: _CompareCard(
                    label: 'Local',
                    side: compare.local,
                    errorMm: compare.localErrorMm,
                    score: compare.localScore,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _CompareCard(
                    label: 'Gemini',
                    side: compare.gemini,
                    errorMm: compare.geminiErrorMm,
                    score: compare.geminiScore,
                  ),
                ),
              ],
            ),
          ],
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
              Expanded(child: _SizeCard(label: 'EU', value: '${_result.eu}')),
              const SizedBox(width: 8),
              Expanded(
                  child: _SizeCard(label: 'US M', value: '${_result.usMen}')),
              const SizedBox(width: 8),
              Expanded(
                  child: _SizeCard(label: 'US W', value: '${_result.usWomen}')),
              const SizedBox(width: 8),
              Expanded(child: _SizeCard(label: 'UK', value: '${_result.uk}')),
            ],
          ),
          if (widget.jobId != null) ...[
            const SizedBox(height: 18),
            const Text(
              'Your truth (cm)',
              style: TextStyle(
                fontWeight: FontWeight.w800,
                color: AppColors.ink,
              ),
            ),
            const SizedBox(height: 6),
            const Text(
              'Enter measured length with a ruler to score this try.',
              style: TextStyle(color: AppColors.muted, fontSize: 13),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _truthCtrl,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    inputFormatters: [
                      FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]')),
                    ],
                    decoration: const InputDecoration(
                      hintText: 'e.g. 26.0',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                FilledButton(
                  onPressed: _saving ? null : _submitTruth,
                  child: Text(_saving ? '…' : 'Save'),
                ),
              ],
            ),
            if (_truthMsg != null) ...[
              const SizedBox(height: 8),
              Text(
                _truthMsg!,
                style: TextStyle(
                  color: _winner != null ? AppColors.ready : AppColors.muted,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ],
          const SizedBox(height: 22),
          FilledButton(
            onPressed: () {
              Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(
                  builder: (_) => MethodScreen(cameras: widget.cameras),
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

class _CompareCard extends StatelessWidget {
  const _CompareCard({
    required this.label,
    required this.side,
    this.errorMm,
    this.score,
  });

  final String label;
  final CompareSide side;
  final double? errorMm;
  final double? score;

  @override
  Widget build(BuildContext context) {
    final cm = side.cm ?? side.cmRaw;
    final err = side.error;
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 14, 12, 14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(
              color: AppColors.muted,
              fontWeight: FontWeight.w700,
              fontSize: 12,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            err != null
                ? 'Failed'
                : (cm == null ? '—' : '${cm.toStringAsFixed(1)} cm'),
            style: const TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w900,
              color: AppColors.ink,
            ),
          ),
          if (err != null)
            Text(
              err,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11, color: AppColors.muted),
            ),
          if (errorMm != null)
            Text(
              '${errorMm! >= 0 ? '+' : ''}${errorMm!.toStringAsFixed(1)} mm',
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: AppColors.muted,
              ),
            ),
          if (score != null)
            Text(
              'score ${score!.toStringAsFixed(2)}',
              style: const TextStyle(fontSize: 11, color: AppColors.muted),
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
