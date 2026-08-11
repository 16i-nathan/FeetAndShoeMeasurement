import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../config.dart';

class ValidateResult {
  ValidateResult({
    required this.ready,
    required this.message,
    required this.hints,
    required this.score,
    required this.checks,
    required this.errors,
  });

  final bool ready;
  final String message;
  final List<String> hints;
  final double score;
  final Map<String, bool> checks;
  final List<String> errors;

  factory ValidateResult.fromJson(Map<String, dynamic> j) {
    final rawChecks = (j['checks'] as Map?) ?? const {};
    return ValidateResult(
      ready: j['ready'] == true,
      message: (j['message'] ?? '') as String,
      hints: ((j['hints'] as List?) ?? const []).map((e) => '$e').toList(),
      score: (j['score'] is num) ? (j['score'] as num).toDouble() : 0,
      checks: rawChecks.map((k, v) => MapEntry('$k', v == true)),
      errors: ((j['errors'] as List?) ?? const []).map((e) => '$e').toList(),
    );
  }
}

class MeasureResult {
  MeasureResult({
    required this.cm,
    required this.eu,
    required this.usMen,
    required this.usWomen,
    required this.uk,
    this.cmRaw,
    this.cmSpread,
    this.confidence,
    this.compare,
    this.backend,
  });

  final double cm;
  final dynamic eu;
  final dynamic usMen;
  final dynamic usWomen;
  final dynamic uk;
  final double? cmRaw;
  final double? cmSpread;
  final double? confidence;
  final CompareBlock? compare;
  final String? backend;

  factory MeasureResult.fromJson(Map<String, dynamic> j) {
    final rawCompare = j['compare'];
    return MeasureResult(
      cm: (j['cm'] as num).toDouble(),
      eu: j['eu'],
      usMen: j['us_men'],
      usWomen: j['us_women'],
      uk: j['uk'],
      cmRaw: j['cm_raw'] is num ? (j['cm_raw'] as num).toDouble() : null,
      cmSpread:
          j['cm_spread'] is num ? (j['cm_spread'] as num).toDouble() : null,
      confidence:
          j['confidence'] is num ? (j['confidence'] as num).toDouble() : null,
      compare: rawCompare is Map<String, dynamic>
          ? CompareBlock.fromJson(rawCompare)
          : null,
      backend: j['backend'] as String?,
    );
  }

  String get displayCm {
    final spread = cmSpread;
    if (spread != null && spread >= 0.15) {
      return '${cm.toStringAsFixed(1)} ± ${spread.toStringAsFixed(1)} cm';
    }
    return '${cm.toStringAsFixed(1)} cm';
  }
}

class CompareSide {
  CompareSide({this.cm, this.cmRaw, this.confidence, this.error});

  final double? cm;
  final double? cmRaw;
  final double? confidence;
  final String? error;

  factory CompareSide.fromJson(Map<String, dynamic>? j) {
    if (j == null) return CompareSide();
    return CompareSide(
      cm: j['cm'] is num ? (j['cm'] as num).toDouble() : null,
      cmRaw: j['cm_raw'] is num ? (j['cm_raw'] as num).toDouble() : null,
      confidence:
          j['confidence'] is num ? (j['confidence'] as num).toDouble() : null,
      error: j['error'] as String?,
    );
  }
}

class CompareBlock {
  CompareBlock({
    required this.local,
    required this.gemini,
    this.truthCm,
    this.localErrorMm,
    this.geminiErrorMm,
    this.localScore,
    this.geminiScore,
  });

  final CompareSide local;
  final CompareSide gemini;
  final double? truthCm;
  final double? localErrorMm;
  final double? geminiErrorMm;
  final double? localScore;
  final double? geminiScore;

  factory CompareBlock.fromJson(Map<String, dynamic> j) {
    final errors = (j['errors_mm'] as Map?) ?? const {};
    final scores = (j['scores'] as Map?) ?? const {};
    return CompareBlock(
      local: CompareSide.fromJson(
        j['local'] is Map<String, dynamic>
            ? j['local'] as Map<String, dynamic>
            : null,
      ),
      gemini: CompareSide.fromJson(
        j['gemini'] is Map<String, dynamic>
            ? j['gemini'] as Map<String, dynamic>
            : null,
      ),
      truthCm: j['truth_cm'] is num ? (j['truth_cm'] as num).toDouble() : null,
      localErrorMm:
          errors['local'] is num ? (errors['local'] as num).toDouble() : null,
      geminiErrorMm:
          errors['gemini'] is num ? (errors['gemini'] as num).toDouble() : null,
      localScore:
          scores['local'] is num ? (scores['local'] as num).toDouble() : null,
      geminiScore:
          scores['gemini'] is num ? (scores['gemini'] as num).toDouble() : null,
    );
  }
}

class TruthSubmitResult {
  TruthSubmitResult({
    required this.truthCm,
    this.winner,
    this.localScore,
    this.geminiScore,
    this.primaryScore,
    this.result,
  });

  final double truthCm;
  final String? winner;
  final double? localScore;
  final double? geminiScore;
  final double? primaryScore;
  final MeasureResult? result;

  factory TruthSubmitResult.fromJson(Map<String, dynamic> j) {
    final scores = (j['scores'] as Map?) ?? const {};
    final result = j['result'];
    return TruthSubmitResult(
      truthCm: (j['truth_cm'] as num).toDouble(),
      winner: j['winner'] as String?,
      localScore:
          scores['local'] is num ? (scores['local'] as num).toDouble() : null,
      geminiScore:
          scores['gemini'] is num ? (scores['gemini'] as num).toDouble() : null,
      primaryScore: scores['primary'] is num
          ? (scores['primary'] as num).toDouble()
          : null,
      result: result is Map<String, dynamic>
          ? MeasureResult.fromJson(result)
          : null,
    );
  }
}

class JobStatus {
  JobStatus({
    required this.id,
    required this.status,
    required this.mode,
    this.message,
    this.result,
    this.previewUrl,
    this.error,
  });

  final String id;
  final String status;
  final String mode;
  final String? message;
  final MeasureResult? result;
  final String? previewUrl;
  final String? error;

  factory JobStatus.fromJson(Map<String, dynamic> j) {
    final result = j['result'];
    return JobStatus(
      id: '${j['id']}',
      status: '${j['status']}',
      mode: '${j['mode']}',
      message: j['message'] as String?,
      result: result is Map<String, dynamic>
          ? MeasureResult.fromJson(result)
          : null,
      previewUrl: j['preview_url'] as String?,
      error: j['error'] as String?,
    );
  }
}

class MeasureApi {
  MeasureApi({String? baseUrl}) : baseUrl = baseUrl ?? apiBaseUrl;

  final String baseUrl;

  Uri _u(String path) => Uri.parse('$baseUrl$path');

  Future<ValidateResult> validateFrame(Uint8List jpeg, String mode) async {
    final req = http.MultipartRequest('POST', _u('/api/validate'));
    req.fields['mode'] = mode;
    req.files.add(
      http.MultipartFile.fromBytes('frame', jpeg, filename: 'frame.jpg'),
    );
    final streamed = await req.send().timeout(const Duration(seconds: 45));
    final body = await streamed.stream.bytesToString();
    if (streamed.statusCode >= 400) {
      throw Exception('Validate failed (${streamed.statusCode}): $body');
    }
    return ValidateResult.fromJson(jsonDecode(body) as Map<String, dynamic>);
  }

  Future<String> createJob(
    Uint8List jpeg,
    String mode, {
    Uint8List? depthNpy,
    double? fx,
    double? fy,
    double? cx,
    double? cy,
  }) async {
    return createBurstJob(
      [jpeg],
      mode,
      depthNpy: depthNpy,
      fx: fx,
      fy: fy,
      cx: cx,
      cy: cy,
    );
  }

  Future<String> createBurstJob(
    List<Uint8List> jpegs,
    String mode, {
    Uint8List? depthNpy,
    double? fx,
    double? fy,
    double? cx,
    double? cy,
  }) async {
    final req = http.MultipartRequest('POST', _u('/api/jobs'));
    req.fields['mode'] = mode;
    if (fx != null) req.fields['fx'] = '$fx';
    if (fy != null) req.fields['fy'] = '$fy';
    if (cx != null) req.fields['cx'] = '$cx';
    if (cy != null) req.fields['cy'] = '$cy';
    if (jpegs.length == 1) {
      req.files.add(
        http.MultipartFile.fromBytes('image', jpegs.first, filename: 'capture.jpg'),
      );
    } else {
      for (var i = 0; i < jpegs.length; i++) {
        req.files.add(
          http.MultipartFile.fromBytes(
            'images',
            jpegs[i],
            filename: 'capture_$i.jpg',
          ),
        );
      }
    }
    if (depthNpy != null) {
      req.files.add(
        http.MultipartFile.fromBytes(
          'depth',
          depthNpy,
          filename: 'depth.npy',
        ),
      );
    }
    final streamed = await req.send().timeout(const Duration(seconds: 90));
    final body = await streamed.stream.bytesToString();
    if (streamed.statusCode >= 400) {
      throw Exception('Job create failed (${streamed.statusCode}): $body');
    }
    final json = jsonDecode(body) as Map<String, dynamic>;
    if (json['error'] != null) {
      throw Exception('${json['error']}');
    }
    return '${json['job_id']}';
  }

  Future<JobStatus> getJob(String jobId) async {
    final res = await http
        .get(_u('/api/jobs/$jobId'))
        .timeout(const Duration(seconds: 15));
    if (res.statusCode >= 400) {
      throw Exception('Job poll failed (${res.statusCode}): ${res.body}');
    }
    return JobStatus.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }

  Future<Map<String, dynamic>> health() async {
    final res = await http
        .get(_u('/api/health'))
        .timeout(const Duration(seconds: 10));
    if (res.statusCode >= 400) {
      throw Exception('Health failed (${res.statusCode}): ${res.body}');
    }
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<TruthSubmitResult> submitTruth(
    String jobId,
    double truthCm, {
    String notes = '',
  }) async {
    final res = await http
        .post(
          _u('/api/jobs/$jobId/truth'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'truth_cm': truthCm, 'notes': notes}),
        )
        .timeout(const Duration(seconds: 30));
    if (res.statusCode >= 400) {
      throw Exception('Truth failed (${res.statusCode}): ${res.body}');
    }
    return TruthSubmitResult.fromJson(
      jsonDecode(res.body) as Map<String, dynamic>,
    );
  }

  Future<JobStatus> waitForJob(
    String jobId, {
    Duration timeout = const Duration(seconds: 120),
  }) async {
    final end = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(end)) {
      final job = await getJob(jobId);
      if (job.status == 'done' ||
          job.status == 'error' ||
          job.status == 'awaiting_depth') {
        return job;
      }
      await Future<void>.delayed(const Duration(milliseconds: 700));
    }
    throw Exception('Measurement timed out');
  }
}
