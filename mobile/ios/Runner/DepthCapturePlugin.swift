import Flutter
import UIKit
import ARKit
import CoreVideo

/// Captures one ARKit scene-depth frame (LiDAR) as JPEG + Float32 meters.
final class DepthCapturePlugin: NSObject, FlutterPlugin, ARSessionDelegate {
  private let channel: FlutterMethodChannel
  private var session: ARSession?
  private var pendingResult: FlutterResult?
  private var timeoutWork: DispatchWorkItem?

  init(channel: FlutterMethodChannel) {
    self.channel = channel
    super.init()
  }

  static func register(with registrar: FlutterPluginRegistrar) {
    let channel = FlutterMethodChannel(
      name: "foot_measure_lab/depth",
      binaryMessenger: registrar.messenger()
    )
    let instance = DepthCapturePlugin(channel: channel)
    registrar.addMethodCallDelegate(instance, channel: channel)
  }

  func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
    switch call.method {
    case "isSupported":
      if #available(iOS 14.0, *) {
        result(ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth))
      } else {
        result(false)
      }
    case "capture":
      capture(result: result)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  private func capture(result: @escaping FlutterResult) {
    guard #available(iOS 14.0, *) else {
      result(FlutterError(code: "unsupported", message: "iOS 14+ required", details: nil))
      return
    }
    guard ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) else {
      result(FlutterError(
        code: "no_lidar",
        message: "This device has no LiDAR / scene depth support.",
        details: nil
      ))
      return
    }
    guard pendingResult == nil else {
      result(FlutterError(code: "busy", message: "Capture already in progress", details: nil))
      return
    }

    pendingResult = result
    let session = ARSession()
    session.delegate = self
    session.delegateQueue = DispatchQueue.main
    self.session = session

    let config = ARWorldTrackingConfiguration()
    config.frameSemantics.insert(.sceneDepth)
    if ARWorldTrackingConfiguration.supportsFrameSemantics(.smoothedSceneDepth) {
      config.frameSemantics.insert(.smoothedSceneDepth)
    }
    session.run(config, options: [.resetTracking, .removeExistingAnchors])

    let timeout = DispatchWorkItem { [weak self] in
      self?.finishError(code: "timeout", message: "Timed out waiting for LiDAR depth. Point at the floor and retry.")
    }
    timeoutWork = timeout
    DispatchQueue.main.asyncAfter(deadline: .now() + 8, execute: timeout)
  }

  func session(_ session: ARSession, didUpdate frame: ARFrame) {
    guard pendingResult != nil else { return }

    let depthData = frame.smoothedSceneDepth ?? frame.sceneDepth
    guard let depthData = depthData else { return }

    timeoutWork?.cancel()
    timeoutWork = nil

    guard let jpeg = Self.jpeg(from: frame.capturedImage) else {
      finishError(code: "jpeg", message: "Failed to encode camera image")
      return
    }
    guard let depthBytes = Self.float32Depth(from: depthData.depthMap) else {
      finishError(code: "depth", message: "Failed to read depth map")
      return
    }

    let depthMap = depthData.depthMap
    let width = CVPixelBufferGetWidth(depthMap)
    let height = CVPixelBufferGetHeight(depthMap)
    // Intrinsics for the full RGB camera image (server resizes depth to RGB)
    let intrinsics = frame.camera.intrinsics

    let payload: [String: Any] = [
      "jpeg": FlutterStandardTypedData(bytes: jpeg),
      "depth": FlutterStandardTypedData(bytes: depthBytes),
      "width": width,
      "height": height,
      "fx": Double(intrinsics[0, 0]),
      "fy": Double(intrinsics[1, 1]),
      "cx": Double(intrinsics[2, 0]),
      "cy": Double(intrinsics[2, 1]),
    ]
    finishOk(payload)
  }

  private func finishOk(_ payload: [String: Any]) {
    let result = pendingResult
    teardown()
    result?(payload)
  }

  private func finishError(code: String, message: String) {
    let result = pendingResult
    teardown()
    result?(FlutterError(code: code, message: message, details: nil))
  }

  private func teardown() {
    timeoutWork?.cancel()
    timeoutWork = nil
    session?.pause()
    session = nil
    pendingResult = nil
  }

  private static func float32Depth(from buffer: CVPixelBuffer) -> Data? {
    CVPixelBufferLockBaseAddress(buffer, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
    guard let base = CVPixelBufferGetBaseAddress(buffer) else { return nil }
    let height = CVPixelBufferGetHeight(buffer)
    let width = CVPixelBufferGetWidth(buffer)
    let bytesPerRow = CVPixelBufferGetBytesPerRow(buffer)
    var out = Data(count: width * height * MemoryLayout<Float32>.size)
    out.withUnsafeMutableBytes { dest in
      guard let dst = dest.bindMemory(to: Float32.self).baseAddress else { return }
      for y in 0..<height {
        let row = base.advanced(by: y * bytesPerRow).assumingMemoryBound(to: Float32.self)
        for x in 0..<width {
          dst[y * width + x] = row[x]
        }
      }
    }
    return out
  }

  private static func jpeg(from pixelBuffer: CVPixelBuffer) -> Data? {
    let ci = CIImage(cvPixelBuffer: pixelBuffer)
    let context = CIContext(options: nil)
    guard let cg = context.createCGImage(ci, from: ci.extent) else { return nil }
    let ui = UIImage(cgImage: cg)
    return ui.jpegData(compressionQuality: 0.9)
  }
}
