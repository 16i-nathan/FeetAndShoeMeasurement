package rw.genius.foot_measure_lab

import android.app.Activity
import android.graphics.ImageFormat
import android.graphics.Point
import android.graphics.Rect
import android.graphics.YuvImage
import android.media.Image
import android.os.Handler
import android.os.Looper
import android.view.Display
import com.google.ar.core.ArCoreApk
import com.google.ar.core.Config
import com.google.ar.core.Session
import com.google.ar.core.exceptions.CameraNotAvailableException
import com.google.ar.core.exceptions.UnavailableException
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean

/** ARCore depth capture → JPEG + Float32 meters. */
class DepthCaptureHandler(
    private val activity: Activity,
) : MethodChannel.MethodCallHandler {
    private var session: Session? = null
    private val capturing = AtomicBoolean(false)
    private val mainHandler = Handler(Looper.getMainLooper())

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "isSupported" -> result.success(isDepthSupported())
            "capture" -> capture(result)
            else -> result.notImplemented()
        }
    }

    private fun isDepthSupported(): Boolean {
        return try {
            when (ArCoreApk.getInstance().checkAvailability(activity)) {
                ArCoreApk.Availability.SUPPORTED_INSTALLED,
                ArCoreApk.Availability.SUPPORTED_APK_TOO_OLD,
                ArCoreApk.Availability.SUPPORTED_NOT_INSTALLED -> {
                    val session = Session(activity)
                    val ok = session.isDepthModeSupported(Config.DepthMode.AUTOMATIC)
                    session.close()
                    ok
                }
                else -> false
            }
        } catch (_: Exception) {
            false
        }
    }

    private fun capture(result: MethodChannel.Result) {
        if (!capturing.compareAndSet(false, true)) {
            result.error("busy", "Capture already in progress", null)
            return
        }
        Thread {
            var lastError: Exception? = null
            // Flutter camera must be released first; retry while the HAL frees the lens.
            repeat(4) { attempt ->
                try {
                    val payload = captureOnce(attempt)
                    mainHandler.post {
                        capturing.set(false)
                        result.success(payload)
                    }
                    return@Thread
                } catch (e: CameraNotAvailableException) {
                    lastError = e
                    closeSession()
                    Thread.sleep(350L * (attempt + 1))
                } catch (e: UnavailableException) {
                    fail(result, "arcore", e.message ?: "ARCore unavailable")
                    return@Thread
                } catch (e: Exception) {
                    lastError = e
                    closeSession()
                    if (attempt < 3) {
                        Thread.sleep(250L * (attempt + 1))
                    }
                }
            }
            val msg = lastError?.message ?: "Depth capture failed"
            val code = when (lastError) {
                is CameraNotAvailableException -> "camera_busy"
                else -> "error"
            }
            val hint = if (code == "camera_busy") {
                "Camera still in use. Close other camera apps, wait a second, then retry."
            } else {
                msg
            }
            fail(result, code, hint)
        }.start()
    }

    private fun captureOnce(attempt: Int): HashMap<String, Any> {
        val install = ArCoreApk.getInstance().requestInstall(activity, true)
        if (install != ArCoreApk.InstallStatus.INSTALLED) {
            throw IllegalStateException("Install / update Google Play Services for AR, then retry.")
        }

        val session = Session(activity)
        if (!session.isDepthModeSupported(Config.DepthMode.AUTOMATIC)) {
            session.close()
            throw IllegalStateException("This Android device does not support ARCore depth.")
        }

        val config = Config(session)
        config.depthMode = Config.DepthMode.AUTOMATIC
        config.updateMode = Config.UpdateMode.LATEST_CAMERA_IMAGE
        config.focusMode = Config.FocusMode.AUTO
        session.configure(config)
        applyDisplayGeometry(session)
        session.resume()
        this.session = session

        // Let ARCore warm up; depth often arrives a few frames after resume.
        val warmupMs = 400L + attempt * 200L
        Thread.sleep(warmupMs)

        val deadline = System.currentTimeMillis() + 12_000
        var payload: HashMap<String, Any>? = null
        var frames = 0
        while (System.currentTimeMillis() < deadline) {
            val frame = try {
                session.update()
            } catch (e: CameraNotAvailableException) {
                throw e
            }
            frames++

            // Skip early frames — depth map is often empty right after resume.
            if (frames < 4) {
                Thread.sleep(40)
                continue
            }

            val cameraImage = try {
                frame.acquireCameraImage()
            } catch (_: Exception) {
                null
            } ?: continue

            val depthImage = try {
                frame.acquireDepthImage16Bits()
            } catch (_: Exception) {
                cameraImage.close()
                null
            } ?: continue

            try {
                val jpeg = yuv420ToJpeg(cameraImage)
                val (depthFloats, w, h) = depth16ToMeters(depthImage)
                if (!hasUsableDepth(depthFloats)) {
                    continue
                }
                val intrinsics = frame.camera.imageIntrinsics
                val focal = intrinsics.focalLength
                val principal = intrinsics.principalPoint
                payload = hashMapOf(
                    "jpeg" to jpeg,
                    "depth" to depthFloats,
                    "width" to w,
                    "height" to h,
                    "fx" to focal[0].toDouble(),
                    "fy" to focal[1].toDouble(),
                    "cx" to principal[0].toDouble(),
                    "cy" to principal[1].toDouble(),
                )
            } finally {
                depthImage.close()
                cameraImage.close()
            }
            if (payload != null) break
            Thread.sleep(40)
        }

        closeSession()
        return payload
            ?: throw IllegalStateException(
                "Timed out waiting for ARCore depth. Point at the floor and retry."
            )
    }

    private fun applyDisplayGeometry(session: Session) {
        try {
            val display: Display = activity.windowManager.defaultDisplay
            val size = Point()
            @Suppress("DEPRECATION")
            display.getRealSize(size)
            session.setDisplayGeometry(display.rotation, size.x, size.y)
        } catch (_: Exception) {
            // Non-fatal — some devices still return depth without this.
        }
    }

    /** Reject empty / all-zero depth maps that look "captured" but are useless. */
    private fun hasUsableDepth(bytes: ByteArray): Boolean {
        val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        var valid = 0
        val n = buf.remaining()
        val step = maxOf(1, n / 2000)
        var i = 0
        while (i < n) {
            val z = buf.get(i)
            if (z.isFinite() && z > 0.05f && z < 5f) valid++
            i += step
        }
        return valid >= 40
    }

    private fun fail(result: MethodChannel.Result, code: String, message: String) {
        closeSession()
        mainHandler.post {
            capturing.set(false)
            result.error(code, message, null)
        }
    }

    private fun closeSession() {
        try {
            session?.pause()
            session?.close()
        } catch (_: Exception) {
        }
        session = null
    }

    private fun depth16ToMeters(image: Image): Triple<ByteArray, Int, Int> {
        val plane = image.planes[0]
        val buffer = plane.buffer.duplicate().order(ByteOrder.LITTLE_ENDIAN)
        val w = image.width
        val h = image.height
        val rowStride = plane.rowStride
        val out = ByteBuffer.allocate(w * h * 4).order(ByteOrder.LITTLE_ENDIAN)
        val row = ByteArray(rowStride)
        for (y in 0 until h) {
            buffer.position(y * rowStride)
            val toRead = minOf(rowStride, buffer.remaining())
            buffer.get(row, 0, toRead)
            for (x in 0 until w) {
                val lo = row[x * 2].toInt() and 0xff
                val hi = row[x * 2 + 1].toInt() and 0xff
                val mm = (hi shl 8) or lo
                out.putFloat(if (mm == 0) 0f else mm / 1000f)
            }
        }
        return Triple(out.array(), w, h)
    }

    private fun yuv420ToJpeg(image: Image): ByteArray {
        val yBuffer = image.planes[0].buffer
        val uBuffer = image.planes[1].buffer
        val vBuffer = image.planes[2].buffer
        val ySize = yBuffer.remaining()
        val uSize = uBuffer.remaining()
        val vSize = vBuffer.remaining()
        val nv21 = ByteArray(ySize + uSize + vSize)
        yBuffer.get(nv21, 0, ySize)
        vBuffer.get(nv21, ySize, vSize)
        uBuffer.get(nv21, ySize + vSize, uSize)
        val yuv = YuvImage(nv21, ImageFormat.NV21, image.width, image.height, null)
        val stream = ByteArrayOutputStream()
        yuv.compressToJpeg(Rect(0, 0, image.width, image.height), 90, stream)
        return stream.toByteArray()
    }
}
