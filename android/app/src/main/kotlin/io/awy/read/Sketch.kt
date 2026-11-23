package io.awy.read

import android.animation.ValueAnimator
import android.content.Context
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.BitmapShader
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorFilter
import android.graphics.ComposePathEffect
import android.graphics.DashPathEffect
import android.graphics.DiscretePathEffect
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PathMeasure
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.view.animation.PathInterpolator
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.random.Random

/*
 * 铅笔手绘风格：和电脑端 ui/js/sketch.js、ui/css/app.css 同一套颜色和画法。
 * - 框线是两笔略带弧度、两头稍微出头的线（第二笔更淡更细），每次打开都重新「画」一遍，所以每次略有不同。
 * - 纸面：米色底 + 很淡的石墨颗粒 + 几道淡淡的铅笔弧线（静止不动，省电）。
 * - 系统关掉动画时，框线不播放「画出来」的动画。
 */

/** 颜色：亮色 / 暗色各一套，数值和电脑端 :root 里的一样。 */
class Palette(
    val paper: Int, val ink: Int, val ink2: Int, val ink3: Int,
    val accent: Int, val warm: Int, val ok: Int, val hatch: Int, val grain: Int, val dark: Boolean
) {
    companion object {
        fun of(context: Context): Palette {
            val night = context.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK
            return if (night == Configuration.UI_MODE_NIGHT_YES) Palette(
                paper = 0xff1c1b19.toInt(), ink = 0xffebe6da.toInt(), ink2 = 0xffb9b3a6.toInt(), ink3 = 0xff847e72.toInt(),
                accent = 0xff93b2d2.toInt(), warm = 0xffd79a76.toInt(), ok = 0xff9cc39e.toInt(),
                hatch = 0x29ebe6da, grain = 0x18ebe6da, dark = true
            ) else Palette(
                paper = 0xfff5f1e8.toInt(), ink = 0xff2a2926.toInt(), ink2 = 0xff57544d.toInt(), ink3 = 0xff8c877c.toInt(),
                accent = 0xff3f6184.toInt(), warm = 0xffa0522d.toInt(), ok = 0xff4f7a52.toInt(),
                hatch = 0x2e2a2926, grain = 0x1c2a2926, dark = false
            )
        }
    }
}

/**
 * 字体：有霞鹜文楷（assets/wenkai.ttf）就用它，没有就用系统衬线字体。
 * 放在 assets 最外层、不放子文件夹：Windows 上打包时子文件夹的路径会被写成反斜杠，手机上就找不到了。
 */
object Fonts {
    private var cached: Typeface? = null
    fun body(context: Context): Typeface = cached ?: run {
        val face = try {
            Typeface.createFromAsset(context.assets, "wenkai.ttf")
        } catch (_: RuntimeException) {
            Typeface.create("serif", Typeface.NORMAL)
        }
        cached = face
        face
    }
}

/**
 * 一圈铅笔框（也可以是圆圈、下划线、一道横线）。
 * hatch 不为 0 时，框里加一层斜线（电脑端的主按钮就是这样）；fill 不为 0 时，框里先涂一层底色（弹出菜单用，盖住下面的内容）。
 */
class SketchDrawable(
    private val density: Float,
    private var color: Int,
    private val shape: Shape = Shape.BOX,
    private val hatch: Int = 0,
    private val seed: Int = Random.nextInt(),
    animate: Boolean = true,
    private val fill: Int = 0
) : Drawable() {
    enum class Shape { BOX, CIRCLE, UNDERLINE, LINE_TOP, LINE_BOTTOM }

    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL; color = fill }
    private val fillRect = RectF()

    private val first = Path()
    private val second = Path()
    private val hatchLines = Path()
    private val inner = RectF()
    private var longest = 1f
    private var progress = if (animate && ValueAnimator.areAnimatorsEnabled()) 0f else 1f
    private var animator: ValueAnimator? = null

    private val jitter = DiscretePathEffect(4f * density, 0.35f * density)   // 线条轻微抖动，像铅笔
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        pathEffect = jitter
    }
    private val hatchPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = density
        color = hatch
    }

    fun setInk(newColor: Int) {
        color = newColor
        invalidateSelf()
    }

    /** 像铅笔一样一笔画出来（delay：一页好几个框时错开一点）。 */
    fun drawIn(delayMs: Long) {
        if (progress >= 1f) return
        animator?.cancel()
        animator = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = 700
            startDelay = delayMs
            interpolator = PathInterpolator(.45f, .1f, .25f, 1f)
            addUpdateListener {
                progress = it.animatedValue as Float
                invalidateSelf()
            }
            start()
        }
    }

    override fun onBoundsChange(bounds: Rect) {
        val pad = 6f * density   // 线两头会出头一点，留出位置，不然会被裁掉
        val l = bounds.left + pad
        val t = bounds.top + pad
        val w = bounds.width() - pad * 2
        val h = bounds.height() - pad * 2
        first.reset()
        second.reset()
        hatchLines.reset()
        if (w <= 0 || h <= 0) return
        fillRect.set(l, t, l + w, t + h)
        draw(first, l, t, w, h, Random(seed))
        draw(second, l, t, w, h, Random(seed * 7 + 13))
        longest = max(w, h) * 1.2f
        if (shape == Shape.CIRCLE) longest = PathMeasure(first, false).length
        if (hatch != 0) {
            inner.set(l + 4 * density, t + 4 * density, l + w - 4 * density, t + h - 4 * density)
            val step = 5 * density
            var x = inner.left - inner.height()
            while (x < inner.right) {
                hatchLines.moveTo(x, inner.bottom)
                hatchLines.lineTo(x + inner.height(), inner.top)
                x += step
            }
        }
    }

    private fun draw(path: Path, l: Float, t: Float, w: Float, h: Float, r: Random) = when (shape) {
        Shape.BOX -> box(path, l, t, w, h, r)
        Shape.CIRCLE -> circle(path, l, t, w, h, r)
        Shape.UNDERLINE -> underline(path, l, t, w, h, r)
        Shape.LINE_TOP -> line(path, l - 4 * density, t, l + w + 4 * density, t + jit(r, density), r, 1.6f)
        Shape.LINE_BOTTOM -> line(path, l - 4 * density, t + h, l + w + 4 * density, t + h + jit(r, density), r, 1.6f)
    }

    private fun jit(r: Random, amount: Float) = (r.nextFloat() - 0.5f) * 2 * amount

    // 一笔略带弧度、两头稍微出头的直线（和 sketch.js 的 stroke() 一样）
    private fun line(path: Path, x1: Float, y1: Float, x2: Float, y2: Float, r: Random, amp: Float) {
        val d = density
        val dx = x2 - x1
        val dy = y2 - y1
        val len = max(hypot(dx, dy), 1f)
        val ux = dx / len
        val uy = dy / len
        val nx = -uy
        val ny = ux
        val o1 = r.nextFloat() * min(5f * d, len * 0.03f)
        val o2 = r.nextFloat() * min(6f * d, len * 0.04f)
        val sx = x1 - ux * o1
        val sy = y1 - uy * o1
        val ex = x2 + ux * o2
        val ey = y2 + uy * o2
        val bend = min(amp * d, len * 0.025f + 0.6f * d)
        val c1 = jit(r, bend)
        val c2 = jit(r, bend)
        val ddx = ex - sx
        val ddy = ey - sy
        path.moveTo(sx, sy)
        path.cubicTo(
            sx + ddx * 0.33f + nx * c1, sy + ddy * 0.33f + ny * c1,
            sx + ddx * 0.66f + nx * c2, sy + ddy * 0.66f + ny * c2,
            ex, ey
        )
    }

    private fun box(path: Path, l: Float, t: Float, w: Float, h: Float, r: Random) {
        val k = 1.4f * density
        val c = arrayOf(
            floatArrayOf(l + jit(r, k), t + jit(r, k)),
            floatArrayOf(l + w + jit(r, k), t + jit(r, k)),
            floatArrayOf(l + w + jit(r, k), t + h + jit(r, k)),
            floatArrayOf(l + jit(r, k), t + h + jit(r, k))
        )
        for (i in 0 until 4) {
            val a = c[i]
            val b = c[(i + 1) % 4]
            line(path, a[0], a[1], b[0], b[1], r, 2.2f)
        }
    }

    private fun circle(path: Path, l: Float, t: Float, w: Float, h: Float, r: Random) {
        val cx = l + w / 2
        val cy = t + h / 2
        val count = 12
        val a0 = r.nextFloat() * PI.toFloat() * 2
        val sweep = PI.toFloat() * 2 + 0.35f + r.nextFloat() * 0.3f   // 多画一点，首尾交叠
        val drift = (if (r.nextFloat() < 0.5f) -1 else 1) * 0.045f
        val pts = (0..count).map { i ->
            val a = a0 + sweep * i / count
            val k = 1 + jit(r, 0.025f) + drift * i / count
            floatArrayOf(cx + cos(a) * w / 2 * k, cy + sin(a) * h / 2 * k)
        }
        path.moveTo(pts[0][0], pts[0][1])
        for (j in 0 until pts.size - 1) {
            val p0 = pts.getOrElse(j - 1) { pts[j] }
            val p1 = pts[j]
            val p2 = pts[j + 1]
            val p3 = pts.getOrElse(j + 2) { p2 }
            path.cubicTo(
                p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
                p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6,
                p2[0], p2[1]
            )
        }
    }

    private fun underline(path: Path, l: Float, t: Float, w: Float, h: Float, r: Random) {
        val d = density
        val y = t + h - 6 * d
        path.moveTo(l - 3 * d, y + jit(r, d))
        path.cubicTo(l + w * 0.3f, y + jit(r, 3 * d), l + w * 0.7f, y + jit(r, 3 * d), l + w + 4 * d, y - d + jit(r, 1.5f * d))
        path.moveTo(l + w * 0.9f, y + 5 * d)
        path.cubicTo(l + w * 0.62f, y + 3 * d + jit(r, 2.5f * d), l + w * 0.36f, y + 6 * d + jit(r, 2.5f * d), l + w * 0.14f, y + 4.5f * d)
    }

    override fun draw(canvas: Canvas) {
        if (fill != 0) canvas.drawRoundRect(fillRect, 3 * density, 3 * density, fillPaint)
        if (hatch != 0 && progress > 0.3f) {
            hatchPaint.alpha = (Color.alpha(hatch) * min(1f, (progress - 0.3f) / 0.7f)).toInt()
            canvas.save()
            canvas.clipRect(inner)
            canvas.drawPath(hatchLines, hatchPaint)
            canvas.restore()
        }
        stroke.pathEffect = if (progress < 1f) {
            ComposePathEffect(DashPathEffect(floatArrayOf(longest * progress, longest), 0f), jitter)
        } else jitter
        stroke.color = color
        stroke.alpha = (Color.alpha(color) * 0.9f).toInt()
        stroke.strokeWidth = 1.5f * density
        canvas.drawPath(first, stroke)
        stroke.alpha = (Color.alpha(color) * 0.45f).toInt()
        stroke.strokeWidth = density
        canvas.drawPath(second, stroke)
    }

    override fun setAlpha(alpha: Int) {}
    override fun setColorFilter(colorFilter: ColorFilter?) {}
    @Deprecated("Deprecated in Java")
    override fun getOpacity() = PixelFormat.TRANSLUCENT
}

/** 纸面背景：底色 + 石墨颗粒 + 几道淡淡的铅笔弧线（像等高线）。 */
class PaperDrawable(private val palette: Palette, private val density: Float) : Drawable() {
    private val grainPaint = Paint().apply {
        shader = BitmapShader(grain(palette.grain), Shader.TileMode.REPEAT, Shader.TileMode.REPEAT)
    }
    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = density
        color = palette.ink
        alpha = if (palette.dark) 16 else 13
        pathEffect = DiscretePathEffect(6f * density, 0.5f * density)
    }
    private val lines = Path()

    override fun onBoundsChange(bounds: Rect) {
        lines.reset()
        val r = Random(11)
        val w = bounds.width().toFloat()
        val h = bounds.height().toFloat()
        val count = 6
        for (i in 0 until count) {
            val y = h * (i + 0.6f) / count
            val swing = h / count * 0.35f
            lines.moveTo(-20 * density, y + (r.nextFloat() - .5f) * swing)
            lines.cubicTo(
                w * 0.3f, y + (r.nextFloat() - .5f) * swing * 2,
                w * 0.7f, y + (r.nextFloat() - .5f) * swing * 2,
                w + 20 * density, y + (r.nextFloat() - .5f) * swing
            )
        }
    }

    override fun draw(canvas: Canvas) {
        canvas.drawColor(palette.paper)
        canvas.drawPath(lines, linePaint)
        canvas.drawRect(bounds, grainPaint)
    }

    override fun setAlpha(alpha: Int) {}
    override fun setColorFilter(colorFilter: ColorFilter?) {}
    @Deprecated("Deprecated in Java")
    override fun getOpacity() = PixelFormat.OPAQUE

    companion object {
        private var grainBitmap: Bitmap? = null
        private var grainColor = 0

        // 颗粒：一张 220×220 的随机深浅小点，平铺开（只生成一次）
        private fun grain(color: Int): Bitmap {
            grainBitmap?.let { if (grainColor == color) return it }
            val size = 220
            val r = Random(5)
            val max = Color.alpha(color)
            val base = color and 0x00ffffff
            val pixels = IntArray(size * size) {
                if (r.nextFloat() < 0.55f) base or ((r.nextFloat() * r.nextFloat() * max * 2).toInt().coerceAtMost(255) shl 24) else 0
            }
            val bitmap = Bitmap.createBitmap(pixels, size, size, Bitmap.Config.ARGB_8888)
            grainBitmap = bitmap
            grainColor = color
            return bitmap
        }
    }
}
