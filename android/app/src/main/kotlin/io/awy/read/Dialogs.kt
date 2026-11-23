package io.awy.read

import android.app.Dialog
import android.graphics.drawable.ColorDrawable
import android.view.Gravity
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import java.time.LocalDate
import java.time.YearMonth

/** 纸面 + 铅笔框的对话框外壳（系统自带的对话框和本 App 的风格不搭）。 */
private fun Ui.sheet(build: (LinearLayout, Dialog) -> Unit): Dialog {
    val dialog = Dialog(activity)
    val box = column().apply {
        background = SketchDrawable(density, p.ink, fill = p.paper, animate = false)
        setPadding(dp(22), dp(18), dp(22), dp(14))
    }
    build(box, dialog)
    dialog.setContentView(box)
    dialog.window?.apply {
        setBackgroundDrawable(ColorDrawable(0))
        setLayout((activity.resources.displayMetrics.widthPixels * 0.9f).toInt(), ViewGroup.LayoutParams.WRAP_CONTENT)
        setDimAmount(0.35f)
    }
    dialog.show()
    return dialog
}

/** 一句话提示，可以带一个动作按钮（比如「去下载」）。 */
fun Ui.say(title: String, message: String, action: Pair<String, () -> Unit>? = null) {
    sheet { box, dialog ->
        box.addView(text(title, 20f))
        box.addView(text(message, 15f, p.ink2), params(8))
        val buttons = row().apply { gravity = Gravity.END }
        if (action != null) buttons.addView(button(action.first, Ui.Btn.PRIMARY) {
            dialog.dismiss()
            action.second()
        })
        buttons.addView(button("好") { dialog.dismiss() }, wrap(10))
        box.addView(buttons, params(14))
    }
}

/**
 * 铅笔风的日历：选中的那天画一个手绘圆圈，今天下面画一道线；还没到的日子是淡的、点不了。
 * 点一下某天就选好了（不用再点「确定」）。
 */
object PencilCalendar {
    private val WEEK = listOf("一", "二", "三", "四", "五", "六", "日")

    fun show(ui: Ui, selected: LocalDate, onPick: (LocalDate) -> Unit) {
        val today = LocalDate.now()
        var month = YearMonth.from(selected)
        ui.sheet { box, dialog ->
            val head = ui.row()
            val prev = ui.button("‹") {}.apply { textSize = 22f }
            val title = ui.text("", 20f).apply { gravity = Gravity.CENTER }
            val next = ui.button("›") {}.apply { textSize = 22f }
            head.addView(prev, LinearLayout.LayoutParams(ui.dp(54), ui.dp(48)))
            head.addView(title, ui.weight())
            head.addView(next, LinearLayout.LayoutParams(ui.dp(54), ui.dp(48)))
            box.addView(head)

            val week = ui.row()
            WEEK.forEach { week.addView(ui.small(it).apply { gravity = Gravity.CENTER }, ui.weight()) }
            box.addView(week, ui.params(10))

            val grid = ui.column()
            box.addView(grid, ui.params(4))

            fun draw() {
                title.text = "${month.year}年${month.monthValue}月"
                ui.enable(next, month < YearMonth.from(today))
                grid.removeAllViews()
                val first = month.atDay(1)
                val offset = first.dayOfWeek.value - 1          // 周一开头
                val cells = offset + month.lengthOfMonth()
                for (r in 0 until (cells + 6) / 7) {
                    val line = ui.row()
                    for (c in 0 until 7) {
                        val n = r * 7 + c - offset + 1
                        val cell: TextView = ui.text("", 17f).apply { gravity = Gravity.CENTER }
                        if (n in 1..month.lengthOfMonth()) {
                            val date = month.atDay(n)
                            cell.text = n.toString()
                            when {
                                date > today -> cell.setTextColor(ui.p.ink3).also { cell.alpha = 0.4f }
                                else -> {
                                    cell.setTextColor(if (date == selected) ui.p.ink else ui.p.ink2)
                                    cell.background = when (date) {
                                        selected -> SketchDrawable(ui.density, ui.p.ink, SketchDrawable.Shape.CIRCLE, animate = false)
                                        today -> SketchDrawable(ui.density, ui.p.ink3, SketchDrawable.Shape.UNDERLINE, animate = false)
                                        else -> null
                                    }
                                    cell.isClickable = true
                                    cell.setOnClickListener {
                                        dialog.dismiss()
                                        onPick(date)
                                    }
                                }
                            }
                        }
                        line.addView(cell, LinearLayout.LayoutParams(0, ui.dp(48), 1f))
                    }
                    grid.addView(line)
                }
            }
            prev.setOnClickListener { month = month.minusMonths(1); draw() }
            next.setOnClickListener { if (month < YearMonth.from(today)) { month = month.plusMonths(1); draw() } }
            draw()

            val buttons = ui.row().apply { gravity = Gravity.END }
            buttons.addView(ui.button("回到今天") {
                dialog.dismiss()
                onPick(today)
            })
            buttons.addView(ui.button("取消") { dialog.dismiss() }, ui.wrap(10))
            box.addView(buttons, ui.params(10))
        }
    }
}
