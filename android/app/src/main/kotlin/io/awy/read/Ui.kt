package io.awy.read

import android.app.Activity
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.BitmapShader
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Shader
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.PopupWindow
import android.widget.TextView
import kotlin.math.min

/** 铅笔手绘风格的界面部件（卡片、按钮、输入框、图标、弹出菜单……），颜色和字号对照电脑端。 */
class Ui(val activity: Activity) {
    val p = Palette.of(activity)
    val density = activity.resources.displayMetrics.density
    private val face = Fonts.body(activity)
    private val toDraw = mutableListOf<SketchDrawable>()
    private var animateNew = true

    enum class Btn { PRIMARY, QUIET, DANGER }

    fun dp(v: Int) = (v * density + 0.5f).toInt()

    /** 新建一圈铅笔框。第一次搭页面时建的框会在页面出来后「画」出来；之后新建的直接显示。 */
    fun sketch(color: Int, shape: SketchDrawable.Shape = SketchDrawable.Shape.BOX, hatch: Int = 0, fill: Int = 0): SketchDrawable =
        SketchDrawable(density, color, shape, hatch, animate = animateNew, fill = fill).also { if (animateNew) toDraw += it }

    fun startDrawing() {
        toDraw.forEachIndexed { i, s -> s.drawIn(min(i, 10) * 70L) }
        toDraw.clear()
        animateNew = false
    }

    fun text(value: CharSequence = "", size: Float = 16f, color: Int = p.ink): TextView = TextView(activity).apply {
        text = value
        textSize = size
        setTextColor(color)
        typeface = face
        setLineSpacing(0f, 1.2f)
        includeFontPadding = true
    }

    fun small(value: CharSequence = "", color: Int = p.ink3) = text(value, 13.5f, color)

    /** 卡片里的小标题（步数、心率……）：铅笔灰，不用彩色。 */
    fun label(value: CharSequence) = text(value, 14f, p.ink2)

    fun column() = LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL }

    fun row() = LinearLayout(activity).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }

    /** 卡片：一圈铅笔框，title 不为空时上面有个标题。 */
    fun card(title: String?): LinearLayout = column().apply {
        background = sketch(p.ink)
        setPadding(dp(20), dp(16), dp(20), dp(16))
        if (title != null) addView(text(title, 20f))
    }

    fun button(label: String, kind: Btn = Btn.QUIET, onClick: () -> Unit): TextView = text(label, 15f).apply {
        gravity = Gravity.CENTER
        minHeight = dp(46)
        minWidth = dp(64)
        setPadding(dp(16), dp(8), dp(16), dp(8))
        setTextColor(
            when (kind) {
                Btn.PRIMARY -> p.ink
                Btn.QUIET -> p.ink2
                Btn.DANGER -> p.warm
            }
        )
        val box = when (kind) {
            Btn.PRIMARY -> sketch(p.ink, hatch = p.hatch)   // 主按钮：框里加斜线，和电脑端一样
            Btn.QUIET -> sketch(p.ink3)
            Btn.DANGER -> sketch(p.warm)
        }
        background = RippleDrawable(ColorStateList.valueOf(p.hatch), box, null)
        isClickable = true
        isFocusable = true
        setOnClickListener { if (isEnabled) onClick() }
    }

    fun enable(view: View, on: Boolean) {
        view.isEnabled = on
        view.alpha = if (on) 1f else 0.45f
    }

    fun input(hint: String, value: String = ""): EditText = EditText(activity).apply {
        setText(value)
        this.hint = hint
        textSize = 16f
        typeface = face
        setTextColor(p.ink)
        setHintTextColor(p.ink3)
        isSingleLine = true
        inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        background = sketch(p.ink3)
        setPadding(dp(16), dp(12), dp(16), dp(12))
    }

    /** 手绘图标（见 Icons.kt）。 */
    fun icon(name: String, sizeDp: Int, color: Int = p.ink): View = View(activity).apply {
        background = Icons.drawable(name, color, density)
        layoutParams = LinearLayout.LayoutParams(dp(sizeDp), dp(sizeDp))
    }

    /** 只有一个图标的圆按钮（顶栏右边的小猫、加号）。 */
    fun iconButton(name: String, description: String, onClick: (View) -> Unit): View = FrameLayout(activity).apply {
        val ic = View(activity).apply { background = Icons.drawable(name, p.ink, density) }
        addView(ic, FrameLayout.LayoutParams(dp(28), dp(28), Gravity.CENTER))
        background = RippleDrawable(ColorStateList.valueOf(p.hatch), null, ColorDrawable(p.ink))
        contentDescription = description
        isClickable = true
        isFocusable = true
        setOnClickListener { onClick(it) }
        layoutParams = LinearLayout.LayoutParams(dp(48), dp(48))
    }

    /** 状态小圆点：绿 = 好了，红褐 = 还要处理。 */
    fun dot(color: Int): View = View(activity).apply {
        background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(color)
            setStroke(dp(3), p.hatch)
        }
        layoutParams = LinearLayout.LayoutParams(dp(13), dp(13)).apply { marginEnd = dp(12) }
    }

    fun params(top: Int = 0) = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
    ).apply { topMargin = dp(top) }

    fun weight() = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)

    fun wrap(start: Int = 0) = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT
    ).apply { marginStart = dp(start) }

    /**
     * 弹出菜单（二级菜单）：纸色底 + 铅笔框，贴在 anchor 下面、靠右。
     * rows：(图标名或 null, 文字, 点了做什么)。点任意一行后菜单收起。
     */
    fun popup(anchor: View, title: String, rows: List<Triple<String?, String, () -> Unit>>) {
        val box = column().apply {
            background = SketchDrawable(density, p.ink, fill = p.paper, animate = false)
            setPadding(dp(18), dp(14), dp(18), dp(10))
            elevation = dp(6).toFloat()
        }
        val window = PopupWindow(box, dp(250), ViewGroup.LayoutParams.WRAP_CONTENT, true)
        box.addView(text(title, 18f).apply {
            background = SketchDrawable(density, p.ink3, SketchDrawable.Shape.LINE_BOTTOM, animate = false)
            setPadding(dp(2), 0, 0, dp(10))
        }, params())
        rows.forEach { (iconName, label, action) ->
            val r = row().apply {
                minimumHeight = dp(50)
                background = RippleDrawable(ColorStateList.valueOf(p.hatch),
                    SketchDrawable(density, p.ink3, SketchDrawable.Shape.LINE_BOTTOM, animate = false), null)
                isClickable = true
                setOnClickListener {
                    window.dismiss()
                    action()
                }
            }
            if (iconName != null) r.addView(icon(iconName, 24, p.ink2).apply {
                (layoutParams as LinearLayout.LayoutParams).marginEnd = dp(10)
            })
            r.addView(text(label, 16f), weight())
            box.addView(r, params(2))
        }
        window.setBackgroundDrawable(ColorDrawable(0))
        window.elevation = dp(8).toFloat()
        window.showAsDropDown(anchor, -dp(200), dp(4))
    }
}

/** 圆形头像：有图就画图，没有就画一个手绘小人；外面一圈铅笔圆。 */
class AvatarView(context: Context, private val ui: Ui) : View(context) {
    private var bitmap: Bitmap? = null
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val placeholder = Icons.drawable("person", ui.p.ink3, ui.density)
    private val ring = SketchDrawable(ui.density, ui.p.ink, SketchDrawable.Shape.CIRCLE, animate = false)

    fun set(b: Bitmap?) {
        bitmap = b
        paint.shader = b?.let { BitmapShader(it, Shader.TileMode.CLAMP, Shader.TileMode.CLAMP) }
        invalidate()
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        ring.setBounds(0, 0, w, h)
        val inset = (w * 0.22f).toInt()
        placeholder.setBounds(inset, inset, w - inset, h - inset)
    }

    override fun onDraw(canvas: Canvas) {
        val b = bitmap
        if (b != null) {
            val r = width / 2f - 5 * ui.density
            canvas.save()
            val scale = (r * 2) / b.width
            canvas.translate(width / 2f - r, height / 2f - r)
            canvas.scale(scale, scale)
            canvas.drawCircle(b.width / 2f, b.height / 2f, b.width / 2f, paint)
            canvas.restore()
        } else {
            placeholder.draw(canvas)
        }
        ring.draw(canvas)
    }
}
