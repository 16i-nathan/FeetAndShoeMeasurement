import 'dart:typed_data';

import 'package:camera/camera.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import '../api/measure_api.dart';
import '../models/measure_method.dart';
import '../theme/app_theme.dart';
import '../widgets/visual_tips.dart';
import 'result_screen.dart';

/// Pick a gallery/file photo and run the same paper measure job as camera capture.
class UploadMeasureScreen extends StatefulWidget {
  const UploadMeasureScreen({
    super.key,
    required this.cameras,
    required this.method,
  });

  final List<CameraDescription> cameras;
  final MeasureMethod method;

  @override
  State<UploadMeasureScreen> createState() => _UploadMeasureScreenState();
}

class _UploadMeasureScreenState extends State<UploadMeasureScreen> {
  final _api = MeasureApi();
  final _picker = ImagePicker();

  Uint8List? _bytes;
  bool _busy = false;
  String? _status;
  String? _error;

  Future<void> _pick() async {
    setState(() {
      _error = null;
      _status = null;
    });
    try {
      final bytes =
          kIsWeb ? await _pickWithFilePicker() : await _pickWithImagePicker();
      if (bytes == null) return;
      setState(() => _bytes = bytes);
    } on MissingPluginException {
      try {
        final bytes = await _pickWithFilePicker();
        if (bytes == null) return;
        setState(() => _bytes = bytes);
      } catch (_) {
        setState(() => _error = 'Restart app');
      }
    } catch (_) {
      setState(() => _error = 'Pick failed');
    }
  }

  Future<Uint8List?> _pickWithImagePicker() async {
    final file = await _picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 92,
      maxWidth: 2400,
    );
    if (file == null) return null;
    return Uint8List.fromList(await file.readAsBytes());
  }

  Future<Uint8List?> _pickWithFilePicker() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.image,
      withData: true,
      allowMultiple: false,
    );
    if (result == null || result.files.isEmpty) return null;
    final file = result.files.first;
    if (file.bytes != null) return file.bytes;
    if (!kIsWeb && file.path != null) {
      return _pickWithImagePicker();
    }
    return null;
  }

  String _short(String raw) {
    final t = raw.trim();
    if (t.isEmpty) return 'Retake';
    if (t.length <= 40) return t;
    return '${t.substring(0, 37).trim()}…';
  }

  Future<void> _measure() async {
    if (_bytes == null || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _status = 'Check…';
    });
    try {
      final v = await _api.validateFrame(_bytes!, widget.method.id);
      if (!v.ready) {
        setState(() {
          _busy = false;
          _error = _short(v.message.isNotEmpty ? v.message : 'Bad photo');
          _status = null;
        });
        return;
      }
      setState(() => _status = 'Measure…');
      final jobId = await _api.createJob(_bytes!, widget.method.id);
      final job = await _api.waitForJob(jobId);
      if (!mounted) return;
      if (job.status == 'done' && job.result != null) {
        await Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => ResultScreen(
              result: job.result!,
              mode: job.mode,
              cameras: widget.cameras,
              previewUrl: job.previewUrl,
            ),
          ),
        );
        return;
      }
      setState(() {
        _busy = false;
        _status = null;
        _error = _short(job.error ?? job.message ?? 'Failed');
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _status = null;
        _error = 'API offline';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Gallery')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
        children: [
          const TipGrid(
            tips: [
              (Icons.vertical_align_top_rounded, 'Top-down'),
              (Icons.description_outlined, 'Full A4'),
              (Icons.accessibility_new_rounded, 'Heel + toes'),
            ],
          ),
          const SizedBox(height: 20),
          AspectRatio(
            aspectRatio: 3 / 4,
            child: Material(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(20),
              child: InkWell(
                borderRadius: BorderRadius.circular(20),
                onTap: _busy ? null : _pick,
                child: Container(
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: AppColors.line),
                  ),
                  clipBehavior: Clip.antiAlias,
                  child: _bytes == null
                      ? const Center(
                          child: Icon(
                            Icons.add_photo_alternate_outlined,
                            size: 56,
                            color: AppColors.primary,
                          ),
                        )
                      : Image.memory(_bytes!, fit: BoxFit.cover),
                ),
              ),
            ),
          ),
          const SizedBox(height: 14),
          OutlinedButton.icon(
            onPressed: _busy ? null : _pick,
            icon: const Icon(Icons.photo_library_outlined),
            label: Text(_bytes == null ? 'Photo' : 'Change'),
          ),
          const SizedBox(height: 10),
          FilledButton(
            onPressed: (_bytes != null && !_busy) ? _measure : null,
            child: Text(_busy ? '…' : 'Measure'),
          ),
          if (_status != null) ...[
            const SizedBox(height: 12),
            Text(
              _status!,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AppColors.muted,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppColors.dangerSoft,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                _error!,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: AppColors.ink,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
