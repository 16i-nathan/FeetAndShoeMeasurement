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
  });

  final bool ready;
  final String message;
  final List<String> hints;
  final double score;

  factory ValidateResult.fromJson(Map<String, dynamic> j) {
    return ValidateResult(
      ready: j['ready'] == true,
      message: (j['message'] ?? '') as String,
      hints: ((j['hints'] as List?) ?? const []).map((e) => '$e').toList(),
      score: (j['score'] is num) ? (j['score'] as num).toDouble() : 0,
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
  });

  final double cm;
  final dynamic eu;
  final dynamic usMen;
  final dynamic usWomen;
  final dynamic uk;

  factory MeasureResult.fromJson(Map<String, dynamic> j) {
    return MeasureResult(
      cm: (j['cm'] as num).toDouble(),
      eu: j['eu'],
      usMen: j['us_men'],
      usWomen: j['us_women'],
      uk: j['uk'],
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
    final streamed = await req.send().timeout(const Duration(seconds: 15));
    final body = await streamed.stream.bytesToString();
    if (streamed.statusCode >= 400) {
      throw Exception('Validate failed (${streamed.statusCode}): $body');
    }
    return ValidateResult.fromJson(jsonDecode(body) as Map<String, dynamic>);
  }

  Future<String> createJob(Uint8List jpeg, String mode) async {
    final req = http.MultipartRequest('POST', _u('/api/jobs'));
    req.fields['mode'] = mode;
    req.files.add(
      http.MultipartFile.fromBytes('image', jpeg, filename: 'capture.jpg'),
    );
    final streamed = await req.send().timeout(const Duration(seconds: 30));
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

  Future<JobStatus> waitForJob(
    String jobId, {
    Duration timeout = const Duration(seconds: 90),
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
