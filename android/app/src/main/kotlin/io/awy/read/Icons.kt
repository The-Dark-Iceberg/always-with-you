package io.awy.read

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorFilter
import android.graphics.DiscretePathEffect
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.drawable.Drawable

/*
 * 手绘图标：和电脑端 ui/js/sketch.js 的 ICONS 同一套笔画（48×48 的格子，SVG 路径写法）。
 * 每个图标画两遍：一笔实的，一笔淡的稍微错开，像铅笔描了两次。
 * 电脑端没有的（房子、上下箭头、四宫格、加号、小黑猫）按同样的手绘风格补画。
 */

object Icons {
    private val defs = mapOf(
        "home" to listOf(
            "M8.6 23.4c5.2-4.9 10.3-9.6 15.5-14.2 5.1 4.6 10.2 9.3 15.4 14.1",
            "M12.8 20.6l-.2 18.8c7.6.3 15.2.3 22.7-.1l-.1-18.6",
            "M21 39.2v-9.6c2-.2 4-.2 6 0l.1 9.5"
        ),
        "transfer" to listOf(
            "M17.4 38.6c-.3-9.5-.2-19.2.2-28.4", "M11.2 16.4c2-2.2 4-4.3 6.2-6.4 2.1 2 4.1 4.2 6 6.4",
            "M30.6 9.4c.3 9.5.2 19.2-.2 28.4", "M24.6 31.8c2 2.2 4 4.3 6 6.4 2.2-2.1 4.2-4.2 6.2-6.4"
        ),
        "heart" to listOf(
            "M24 39.4c-8.3-5.8-14.3-11.4-14.6-18.2-.2-5 3.3-8.6 7.6-8.6 3.2 0 5.6 1.9 7 4.6 1.4-2.8 3.9-4.7 7.1-4.6 4.4.1 7.7 3.8 7.4 8.8-.4 6.8-6.4 12.3-14.5 18"
        ),
        "grid" to listOf(
            "M10.2 10.6c3.8-.2 7.7-.2 11.4 0l-.1 11.2c-3.8.2-7.6.2-11.4 0l.1-11.2",
            "M26.4 10.4c3.8-.2 7.7-.1 11.4.1l-.2 11.2c-3.8.2-7.6.1-11.3 0l.1-11.3",
            "M10.4 26.4c3.8-.2 7.6-.2 11.3 0l-.1 11.3c-3.8.2-7.6.2-11.4 0l.2-11.3",
            "M26.3 26.3c3.8-.2 7.7-.1 11.5.1l-.2 11.2c-3.8.2-7.6.2-11.3 0v-11.3"
        ),
        "gear" to listOf(
            "M24.2 18.6c3 .1 5.4 2.6 5.3 5.6-.1 3-2.6 5.4-5.7 5.2-2.9-.1-5.2-2.6-5.1-5.6.1-2.9 2.5-5.3 5.5-5.2",
            "M21.6 8.6l4.9-.1.9 4.6 3.4 1.5 3.9-2.7 3.5 3.5-2.7 3.9 1.5 3.4 4.6.9v4.9l-4.6.9-1.5 3.4 2.7 3.9-3.5 3.5-3.9-2.7-3.4 1.5-.9 4.6h-4.9l-.9-4.6-3.4-1.5-3.9 2.7-3.5-3.5 2.7-3.9-1.5-3.4-4.6-.9.1-4.9 4.6-.9 1.4-3.4-2.7-3.9 3.5-3.5 3.9 2.7 3.4-1.5.9-4.6"
        ),
        "plus" to listOf("M24.2 10.4c-.3 9.3-.2 18.4.1 27.4", "M10.6 24.4c9.2-.4 18.3-.3 27.2.1"),
        "person" to listOf(
            "M24.6 9.2c4.3.2 7.4 3.6 7.2 7.8-.2 4.3-3.6 7.4-7.9 7.2-4.2-.2-7.3-3.7-7.1-7.9.3-4.1 3.6-7.2 7.6-7.1",
            "M9.8 40.6c.6-7.4 6.4-12.6 14.2-12.7 7.9-.1 13.6 5.1 14.4 12.5"
        ),
        "box" to listOf(
            "M8.4 17.6 24.2 10.4l15.6 7.3L24 24.9 8.4 17.6", "M8.4 17.9v16.4L24 41.6l15.8-7.4V17.8", "M24 25v16.4",
            "M8.4 17.6 4.6 23l15.6 7.3 3.8-5.2", "M39.8 17.8l3.7 5.3-15.7 7.2-3.8-5.3"
        ),
        "link" to listOf(
            "M21 13.5h-8.2c-1.7 0-2.8 1.1-2.8 2.8v19.1c0 1.7 1.1 2.8 2.8 2.8h19.3c1.7 0 2.8-1.1 2.8-2.8v-8",
            "M27.4 9.6l11.1.2-.1 11", "M38.2 9.9 22.8 25.2"
        ),
        "download" to listOf(
            "M24.2 9.5c-.2 8.3-.1 16.4.1 23.6", "M15.6 25.2c2.9 2.8 5.7 5.6 8.6 8.6 2.8-3 5.6-5.8 8.4-8.7",
            "M10.2 39.4c9.3-.5 18.6-.4 27.8.2"
        ),
        "spark" to listOf(
            "M24.1 8.6c1.1 6.6 3.6 9.6 10.6 11.1-6.9 1.4-9.5 4.4-10.6 11.2-1.2-6.8-3.8-9.8-10.7-11.2 6.9-1.5 9.6-4.5 10.7-11.1",
            "M36.6 30.2c.4 2.6 1.4 3.6 4.1 4.2-2.7.5-3.7 1.6-4.1 4.2-.5-2.6-1.5-3.7-4.2-4.2 2.7-.6 3.7-1.6 4.2-4.2"
        ),
        "cat" to listOf("M31.6 40.2c4.9.6 9.5-1.2 10.6-5.4.8-3.2-1-5.8-3.8-5.8"),   // 尾巴（猫身是下面的填充）
    )

    /** 小黑猫的身体（坐着、两只尖耳朵），涂满墨色。 */
    private const val CAT_BODY =
        "M14.6 41.2c-2.4-4.6-2.6-9.9-.7-14.7 1-2.6 2.6-4.6 4.4-6.1-1.9-1.7-2.9-4-2.9-6.6 0-1 .2-2 .5-2.9" +
            "L15.2 4.8l5.5 4.9c1-.3 2.1-.4 3.3-.4s2.3.1 3.3.4l5.5-4.9-1 6.1c.3.9.5 1.9.5 2.9 0 2.6-1 4.9-2.9 6.6" +
            " 1.8 1.5 3.4 3.5 4.4 6.1 1.9 4.8 1.7 10.1-.7 14.7z"

    fun drawable(name: String, color: Int, density: Float): IconDrawable {
        val paths = (defs[name] ?: emptyList()).map(Svg::parse)
        val fill = if (name == "cat") Svg.parse(CAT_BODY) else null
        return IconDrawable(paths, fill, color, density)
    }
}

class IconDrawable(
    private val paths: List<Path>, private val fill: Path?, private var color: Int, density: Float
) : Drawable() {
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        pathEffect = DiscretePathEffect(3f, 0.22f)   // 48 格坐标里的抖动
    }
    private val solid = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }

    fun setInk(c: Int) {
        color = c
        invalidateSelf()
    }

    override fun draw(canvas: Canvas) {
        val b = bounds
        if (b.isEmpty) return
        canvas.save()
        canvas.translate(b.left.toFloat(), b.top.toFloat())
        canvas.scale(b.width() / 48f, b.height() / 48f)
        fill?.let {
            solid.color = color
            canvas.drawPath(it, solid)
        }
        stroke.color = color
        stroke.alpha = (Color.alpha(color) * 0.92f).toInt()
        stroke.strokeWidth = 2.4f
        paths.forEach { canvas.drawPath(it, stroke) }
        fill?.let { canvas.drawPath(it, stroke) }
        canvas.translate(.8f, .6f)
        stroke.alpha = (Color.alpha(color) * 0.4f).toInt()
        stroke.strokeWidth = 1.3f
        paths.forEach { canvas.drawPath(it, stroke) }
        canvas.restore()
    }

    override fun setAlpha(alpha: Int) {}
    override fun setColorFilter(colorFilter: ColorFilter?) {}
    @Deprecated("Deprecated in Java")
    override fun getOpacity() = PixelFormat.TRANSLUCENT
}

/** 读 SVG 路径（M L H V C S Q Z 和小写的相对写法，数字可以写成 "1.6.2" 这种紧凑形式）。只给上面的图标用。 */
object Svg {
    fun parse(d: String): Path {
        val path = Path()
        var i = 0
        var x = 0f
        var y = 0f
        var startX = 0f
        var startY = 0f
        var lastCx = 0f
        var lastCy = 0f
        var cmd = 'M'

        fun skip() {
            while (i < d.length && (d[i] == ' ' || d[i] == ',' || d[i] == '\n')) i++
        }

        fun num(): Float {
            skip()
            val s = i
            if (i < d.length && (d[i] == '-' || d[i] == '+')) i++
            var dot = false
            while (i < d.length && (d[i].isDigit() || (d[i] == '.' && !dot))) {
                if (d[i] == '.') dot = true
                i++
            }
            return d.substring(s, i).toFloat()
        }

        while (true) {
            skip()
            if (i >= d.length) break
            if (d[i].isLetter()) {
                cmd = d[i]
                i++
            }
            val rel = cmd.isLowerCase()
            val ox = if (rel) x else 0f
            val oy = if (rel) y else 0f
            when (cmd.uppercaseChar()) {
                'M' -> {
                    x = ox + num(); y = oy + num()
                    path.moveTo(x, y)
                    startX = x; startY = y
                    cmd = if (rel) 'l' else 'L'   // M 后面接着的坐标当作 L
                }
                'L' -> { x = ox + num(); y = oy + num(); path.lineTo(x, y) }
                'H' -> { x = ox + num(); path.lineTo(x, y) }
                'V' -> { y = oy + num(); path.lineTo(x, y) }
                'C' -> {
                    val x1 = ox + num(); val y1 = oy + num()
                    val x2 = ox + num(); val y2 = oy + num()
                    x = ox + num(); y = oy + num()
                    path.cubicTo(x1, y1, x2, y2, x, y)
                    lastCx = x2; lastCy = y2
                }
                'S' -> {
                    val x1 = 2 * x - lastCx; val y1 = 2 * y - lastCy
                    val x2 = ox + num(); val y2 = oy + num()
                    x = ox + num(); y = oy + num()
                    path.cubicTo(x1, y1, x2, y2, x, y)
                    lastCx = x2; lastCy = y2
                }
                'Q' -> {
                    val x1 = ox + num(); val y1 = oy + num()
                    x = ox + num(); y = oy + num()
                    path.quadTo(x1, y1, x, y)
                }
                'Z' -> { path.close(); x = startX; y = startY }
                else -> i++
            }
            if (cmd.uppercaseChar() != 'C' && cmd.uppercaseChar() != 'S') { lastCx = x; lastCy = y }
        }
        return path
    }
}
