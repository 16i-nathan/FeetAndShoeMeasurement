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
  private var framesSeen = 0
  private var mode: Mode = .idle

  private enum Mode {
    case idle
    case warmUp
    case capture
  }

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
    case "warmUp":
      warmUp(result: result)
    case "capture":
      capture(result: result)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  private func warmUp(result: @escaping FlutterResult) {
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
      result(FlutterError(code: "busy", message: "Depth already running", details: nil))
      return
    }

    pendingResult = result
    mode = .warmUp
    framesSeen = 0
    startSession(timeoutSeconds: 3.5)
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
    mode = .capture
    framesSeen = 0
    startSession(timeoutSeconds: 18)
  }

  @available(iOS 14.0, *)
  private func startSession(timeoutSeconds: Double) {
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

    timeoutWork?.cancel()
    let timeout = DispatchWorkItem { [weak self] in
      guard let self = self else { return }
      if self.mode == .warmUp {
        // Warm-up is best-effort — succeeding at starting the session is enough.
        self.finishOk(["ok": true, "frames": self.framesSeen])
      } else {
        self.finishError(
          code: "timeout",
          message: "Depth sensor still waking. Point at the floor and tap Capture again."
        )
      }
    }
    timeoutWork = timeout
    DispatchQueue.main.asyncAfter(deadline: .now() + timeoutSeconds, execute: timeout)
  }

  func session(_ session: ARSession, didFailWithError error: Error) {
    guard pendingResult != nil else { return }
    let ns = error as NSError
    if mode == .warmUp {
      finishError(
        code: "camera_busy",
        message: "Camera still in use. Wait a second, then open Depth again."
      )
      return
    }
    if ns.domain == "com.apple.arkit.error" || ns.localizedDescription.lowercased().contains("camera") {
      finishError(
        code: "camera_busy",
        message: "Camera still in use. Wait a second, then retry Depth capture."
      )
      return
    }
    finishError(code: "error", message: error.localizedDescription)
  }

  func sessionWasInterrupted(_ session: ARSession) {
    // Ignore transient interruptions while waiting; timeout will fire if needed.
  }

  func sessionInterruptionEnded(_ session: ARSession) {
    guard #available(iOS 14.0, *), pendingResult != nil else { return }
    let config = ARWorldTrackingConfiguration()
    config.frameSemantics.insert(.sceneDepth)
    if ARWorldTrackingConfiguration.supportsFrameSemantics(.smoothedSceneDepth) {
      config.frameSemantics.insert(.smoothedSceneDepth)
    }
    session.run(config, options: [])
  }

  func session(_ session: ARSession, didUpdate frame: ARFrame) {
    guard pendingResult != nil else { return }
    framesSeen += 1

    if mode == .warmUp {
      // Enough frames to wake LiDAR / tracking, then finish.
      if framesSeen >= 12 {
        finishOk(["ok": true, "frames": framesSeen])
      }
      return
    }

    // Depth is often empty for the first frames after run().
    if framesSeen < 8 { return }

    let depthData = frame.smoothedSceneDepth ?? frame.sceneDepth
    guard let depthData = depthData else { return }

    guard let depthBytes = Self.float32Depth(from: depthData.depthMap),
          Self.hasUsableDepth(depthBytes) else {
      return
    }

    timeoutWork?.cancel()
    timeoutWork = nil

    guard let jpeg = Self.jpeg(from: frame.capturedImage) else {
      finishError(code: "jpeg", message: "Failed to encode camera image")
      return
    }

    let depthMap = depthData.depthMap
    let width = CVPixelBufferGetWidth(depthMap)
    let height = CVPixelBufferGetHeight(depthMap)
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
    framesSeen = 0
    mode = .idle
  }

  private static func hasUsableDepth(_ data: Data) -> Bool {
    data.withUnsafeBytes { raw in
      let floats = raw.bindMemory(to: Float32.self)
      let n = floats.count
      guard n > 0 else { return false }
      let step = max(1, n / 2000)
      var valid = 0
      var i = 0
      while i < n {
        let z = floats[i]
        if z.isFinite && z > 0.05 && z < 5 { valid += 1 }
        i += step
      }
      return valid >= 40
    }
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
