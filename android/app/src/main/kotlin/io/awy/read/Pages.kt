package io.awy.read

import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.health.connect.HealthConnectException
import android.health.connect.HealthConnectManager
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** 一页：可以上下滚动；每次切到这页（或从别处回来）都重新画一遍，数据在后台读好再填进去。 */
abstract class Page(val a: MainActivity) {
    val ui: Ui get() = a.ui
    val body: LinearLayout = a.ui.column().apply { setPadding(a.ui.dp(18), a.ui.dp(14), a.ui.dp(18), a.ui.dp(24)) }
    val view: ScrollView = ScrollView(a).apply {
        isFillViewport = true
        overScrollMode = View.OVER_SCROLL_NEVER
        addView(body)
    }

    abstract fun show()

    /** 后台读，读完回到界面线程填；期间换了页就不填了。 */
    fun <T> load(work: () -> T, fill: (T) -> Unit) {
        val v = a.version
        a.worker.execute {
            val result = try {
                work()
            } catch (e: Exception) {
                null
            }
            a.runOnUiThread { if (v == a.version && !a.isDestroyed && result != null) fill(result) }
        }
    }

    /** 日期：‹ [今天 · 11月22日] ›，点中间弹出铅笔风日历。健康和应用两页共用同一个日子。 */
    fun dateNav(): View = ui.row().apply {
        val today = LocalDate.now()
        val prev = ui.button("‹") { a.day = a.day.minusDays(1); show() }.apply { textSize = 24f; contentDescription = "前一天" }
        val label = a.day.format(DateTimeFormatter.ofPattern(if (a.day.year == today.year) "M月d日" else "yyyy年M月d日"))
        val mid = ui.button(if (a.day == today) "今天 · $label" else label, Ui.Btn.PRIMARY) {
            PencilCalendar.show(ui, a.day) { a.day = it; show() }
        }.apply {
            isSingleLine = true
            ellipsize = android.text.TextUtils.TruncateAt.END
            setPadding(ui.dp(8), ui.dp(8), ui.dp(8), ui.dp(8))
            contentDescription = "选择日期，$text"
        }
        val next = ui.button("›") { if (a.day < today) { a.day = a.day.plusDays(1); show() } }.apply { textSize = 24f; contentDescription = "后一天" }
        ui.enable(next, a.day < today)
        addView(prev, LinearLayout.LayoutParams(ui.dp(58), ui.dp(56)))
        addView(mid, LinearLayout.LayoutParams(0, ui.dp(56), 1f).apply { marginStart = ui.dp(8); marginEnd = ui.dp(8) })
        addView(next, LinearLayout.LayoutParams(ui.dp(58), ui.dp(56)))
    }

    fun note(text: String) = body.addView(ui.small(text).apply { setPadding(ui.dp(4), 0, ui.dp(4), 0) }, ui.params(16))
}

// ---- 主页：今天的概览 ----------------------------------------------------------------

class HomePage(a: MainActivity) : Page(a) {
    private class Stats(
        val steps: Long?, val heart: String?, val sleep: String?, val screen: Long?, val top: List<Pair<String, Long>>?
    )

    override fun show() {
        body.removeAllViews()
        val now = LocalTime.now()
        val hello = when (now.hour) {
            in 5..10 -> "早上好"
            in 11..13 -> "中午好"
            in 14..17 -> "下午好"
            else -> "晚上好"
        }
        val name = Sync.prefs(a).getString("my_name", "").orEmpty()
        body.addView(ui.text(if (name.isBlank()) hello else "$hello，$name", 26f))
        val week = "一二三四五六日"[LocalDate.now().dayOfWeek.value - 1]
        body.addView(ui.small(LocalDate.now().format(DateTimeFormatter.ofPattern("M月d日")) + " · 周$week"), ui.params(2))

        val today = ui.card("今天")
        val grid1 = ui.row()
        val grid2 = ui.row()
        val steps = tile(grid1, "步数")
        val screen = tile(grid1, "亮屏")
        val heart = tile(grid2, "心率")
        val sleep = tile(grid2, "昨晚睡眠")
        today.addView(grid1, ui.params(10))
        today.addView(grid2, ui.params(12))
        body.addView(today, ui.params(16))

        val most = ui.card("用得最多")
        val mostBody = ui.column()
        mostBody.addView(ui.small("正在读取"))
        most.addView(mostBody, ui.params(6))
        body.addView(most, ui.params(14))

        val pc = ui.card("电脑")
        val link = PcLink(a)
        if (link.paired) {
            val last = link.lastUpload
            pc.addView(ui.text("已配对：${link.pcName}", 16f), ui.params(6))
            pc.addView(ui.small((if (last > 0) "上次上传 ${a.time(last)}" else "还没上传过") + " · 待上传 ${Sync.pending(a)} 条"), ui.params(2))
            pc.addView(ui.button(if (a.syncing) "正在同步…" else "立即同步", Ui.Btn.PRIMARY) { a.syncNow(quiet = false) }
                .also { ui.enable(it, !a.syncing) }, ui.wrap())
        } else {
            pc.addView(ui.small("还没和电脑配对。配对后，手机上的这些会在连同一个 Wi-Fi 时传给电脑，整理成记忆。"), ui.params(6))
            pc.addView(ui.button("去配对", Ui.Btn.PRIMARY) { a.show("pc") }, ui.wrap())
        }
        (pc.getChildAt(pc.childCount - 1).layoutParams as LinearLayout.LayoutParams).topMargin = ui.dp(10)
        body.addView(pc, ui.params(14))
        note("数据只在这台手机和你自己的电脑之间传，不经过任何服务器。")

        load({ read() }) { s ->
            steps.text = s.steps?.let { "%,d 步".format(it) } ?: "—"
            screen.text = s.screen?.let { duration(it) } ?: "—"
            heart.text = s.heart ?: "—"
            sleep.text = s.sleep ?: "—"
            mostBody.removeAllViews()
            when {
                s.top == null -> mostBody.addView(ui.small("还没打开「使用情况访问权限」，在「设置」里打开。"))
                s.top.isEmpty() -> mostBody.addView(ui.small("今天还没怎么用手机。"))
                else -> s.top.forEach { (name, ms) ->
                    val r = ui.row()
                    r.addView(ui.text(name, 15f, ui.p.ink2), ui.weight())
                    r.addView(ui.text(duration(ms), 15f, ui.p.ink3))
                    mostBody.addView(r, ui.params(4))
                }
            }
        }
    }

    private fun tile(row: LinearLayout, title: String): TextView {
        val col = ui.column()
        col.addView(ui.label(title))
        val value = ui.text("…", 20f)
        col.addView(value)
        row.addView(col, ui.weight())
        return value
    }

    private fun read(): Stats {
        val zone = ZoneId.systemDefault()
        val start = LocalDate.now().atStartOfDay(zone).toInstant()
        val now = Instant.now()
        var steps: Long? = null
        var heart: String? = null
        var sleep: String? = null
        val manager = a.getSystemService(HealthConnectManager::class.java)
        val canSteps = Sync.granted(a, Metric.STEPS.readPermission)
        val canHeart = Sync.granted(a, Metric.HEART.readPermission)
        if (manager != null && (canSteps || canHeart || Sync.granted(a, Metric.SLEEP.readPermission))) {
            HealthExport(manager, a::sourceLabel).use { export ->
                if (canSteps || canHeart) {
                    val hours = export.hours(start, now, canSteps, canHeart)
                    if (canSteps) steps = hours.sumOf { it.steps ?: 0 }
                    hours.lastOrNull { it.hrAvg != null }?.let {
                        heart = "${it.hrAvg} 次/分"
                    }
                }
                if (Sync.granted(a, Metric.SLEEP.readPermission)) {
                    export.sleep(start.minus(Duration.ofHours(14)), now).filter { it.end > start }.maxByOrNull { it.end }?.let {
                        sleep = duration(Duration.between(it.start, it.end).toMillis())
                    }
                }
            }
        }
        val reader = UsageReader(a)
        var screen: Long? = null
        var top: List<Pair<String, Long>>? = null
        if (reader.granted()) {
            val s = start.toEpochMilli()
            val e = now.toEpochMilli()
            val read = reader.read(s - 2 * 3600_000L, e)
            screen = read.screens.sumOf { maxOf(0L, minOf(it.end, e) - maxOf(it.start, s)) }
            val per = HashMap<String, Long>()
            read.apps.forEach { x -> (minOf(x.end, e) - maxOf(x.start, s)).takeIf { it > 0 }?.let { per[x.pkg] = (per[x.pkg] ?: 0) + it } }
            top = per.entries.sortedByDescending { it.value }.filter { it.value >= 60_000 }.take(3).map { reader.label(it.key) to it.value }
        }
        return Stats(steps, heart, sleep, screen, top)
    }
}

// ---- 配对传输 ----------------------------------------------------------------

class PcPage(a: MainActivity) : Page(a) {
    private var codeInput: EditText? = null
    private var hostInput: EditText? = null
    private var message = ""
    private var pairing = false

    override fun show() {
        body.removeAllViews()
        val card = ui.card("电脑")
        val link = PcLink(a)
        if (!link.paired) {
            card.addView(ui.small("在电脑上打开 AlwaysWithYou →「设置 → 手机」，点「配对新手机」，把显示的配对码填在这里。手机和电脑要连同一个 Wi-Fi。"), ui.params(6))
            val code = ui.input("12 位配对码", codeInput?.text?.toString().orEmpty())
            codeInput = code
            card.addView(code, ui.params(12))
            val host = ui.input("电脑地址（一般不用填）", hostInput?.text?.toString().orEmpty())
            hostInput = host
            card.addView(host, ui.params(8))
            card.addView(ui.small("找不到电脑时再填：电脑上「设置 → 手机」里写着地址，比如 192.168.1.5"), ui.params(4))
            val button = ui.button(if (pairing) "正在配对…" else "配对", Ui.Btn.PRIMARY) { pair() }
            ui.enable(button, !pairing)
            card.addView(button, ui.params(12))
        } else {
            card.addView(ui.text("已配对：${link.pcName}", 17f), ui.params(6))
            val last = link.lastUpload
            card.addView(ui.small(
                (if (last > 0) "上次上传 ${a.time(last)}" else "还没上传过") + " · 待上传 ${Sync.pending(a)} 条" +
                    if (link.onWifi()) "" else " · 现在没连 Wi-Fi"
            ), ui.params(4))
            link.lastError.takeIf { it.isNotEmpty() }?.let { card.addView(ui.small(it, ui.p.warm), ui.params(4)) }
            val buttons = ui.row()
            val sync = ui.button(if (a.syncing) "正在同步…" else "立即同步", Ui.Btn.PRIMARY) {
                a.syncNow(quiet = false) { message = it }
            }
            ui.enable(sync, !a.syncing)
            buttons.addView(sync)
            buttons.addView(ui.button("取消配对", Ui.Btn.DANGER) {
                link.unpair()
                message = "已取消配对。电脑上也记得删掉这台手机"
                show()
            }, ui.wrap(10))
            card.addView(buttons, ui.params(12))
        }
        if (message.isNotEmpty()) card.addView(ui.small(message, ui.p.ink2), ui.params(10))
        body.addView(card)

        val history = Sync.history(a)
        val log = ui.card("传输记录")
        if (history.isEmpty()) log.addView(ui.small("还没有。"), ui.params(6))
        history.take(10).forEach { (t, m, bg) ->
            val r = ui.column()
            r.addView(ui.small(a.time(t) + if (bg) " · 后台" else " · 手动"))
            r.addView(ui.text(m, 15f, ui.p.ink2))
            log.addView(r, ui.params(8))
        }
        body.addView(log, ui.params(14))
        note("只在同一个 Wi-Fi 里传，内容是加密的；不在家时先存在手机上，回家再传。后台大约每小时读一次、传一次。")
    }

    private fun localNetworkNeeded(): Boolean = try {
        a.packageManager.getPermissionInfo(LOCAL_NETWORK, 0)
        !Sync.granted(a, LOCAL_NETWORK)
    } catch (_: PackageManager.NameNotFoundException) {
        false   // 系统没有这项权限（老版本安卓）：不用申请
    }

    fun afterLocalNetwork(granted: Boolean) {
        if (granted) pair() else {
            message = "没有「附近的设备」权限，手机找不到局域网里的电脑"
            show()
        }
    }

    private fun pair() {
        val code = codeInput?.text?.toString().orEmpty()
        val host = hostInput?.text?.toString().orEmpty()
        if (Crypto.normalizeCode(code).length != 12) {
            message = "配对码是 12 位，比如 7K3Q-9XMD-2PLF"
            show()
            return
        }
        if (localNetworkNeeded()) {
            a.requestPermissions(arrayOf(LOCAL_NETWORK), LOCAL_NETWORK_REQUEST)
            return
        }
        pairing = true
        message = "正在找电脑……"
        show()
        a.worker.execute {
            val result = try {
                val name = PcLink(a).pair(code, host)
                "已和 $name 配对。" + Sync.run(a.applicationContext, background = false)
            } catch (e: PairError) {
                e.message ?: "配对失败"
            } catch (e: Exception) {
                "配对失败：${e.message}"
            }
            a.runOnUiThread {
                pairing = false
                message = result
                if (PcLink(a).paired) {
                    codeInput = null
                    hostInput = null
                }
                if (a.current == "pc") show()
            }
        }
    }
}

// ---- 健康 ----------------------------------------------------------------

class HealthPage(a: MainActivity) : Page(a) {
    private class MetricCard(val value: TextView, val detail: LinearLayout)

    override fun show() {
        body.removeAllViews()
        body.addView(dateNav())
        val status = ui.row()
        val readStatus = ui.small()
        status.addView(readStatus, ui.weight())
        status.addView(ui.button("立即读取") { show() })
        body.addView(status, ui.params(6))

        val card = ui.card("健康")
        val cards = LinkedHashMap<Metric, MetricCard>()
        Metric.entries.forEachIndexed { i, metric ->
            val block = ui.column()
            block.addView(ui.label(a.getString(metric.title)))
            val value = ui.text("", 20f)
            val detail = ui.column()
            block.addView(value, ui.params(2))
            block.addView(detail)
            cards[metric] = MetricCard(value, detail)
            card.addView(block, ui.params(if (i == 0) 10 else 16))
        }
        body.addView(card, ui.params(10))
        note("数据来自系统的健康数据（手表要先同步到手机，比如欢太健康）。同一项有好几个来源时，「系统汇总」已经去掉了重复。")

        val reader = a.healthReader
        val granted = if (reader == null) emptyList() else Metric.entries.filter { Sync.granted(a, it.readPermission) }
        cards.forEach { (metric, c) ->
            status(c, when {
                reader == null -> "这台手机用不了系统的健康数据"
                metric in granted -> "正在读取"
                else -> "等待授权（在「设置」里授权）"
            })
        }
        readStatus.text = if (granted.isEmpty()) "" else "正在读取"
        if (reader == null) return
        val v = a.version
        val zone = ZoneId.systemDefault()
        var outstanding = granted.size
        var hadError = false
        granted.forEach { metric ->
            reader.read(metric, a.day, zone) { result ->
                a.runOnUiThread {
                    if (v != a.version || a.isDestroyed) return@runOnUiThread
                    val c = cards.getValue(metric)
                    result.fold({ reading ->
                        if (reading == null) status(c, "当天没有记录") else reading(c, reading)
                    }, { error ->
                        hadError = true
                        status(c, when {
                            error is SecurityException ||
                                error is HealthConnectException && error.errorCode == HealthConnectException.ERROR_SECURITY ->
                                "当前权限读不到这段时间的记录"
                            else -> "读取失败，请重试"
                        })
                    })
                    if (--outstanding == 0) {
                        val at = "读取时间 " + LocalTime.now(zone).format(DateTimeFormatter.ofPattern("HH:mm:ss"))
                        readStatus.text = if (hadError) "$at · 部分项目读取失败" else at
                    }
                }
            }
        }
    }

    private fun status(c: MetricCard, text: String) {
        c.value.text = text
        c.value.textSize = 15f
        c.value.setTextColor(ui.p.ink3)
        c.detail.removeAllViews()
    }

    private fun reading(c: MetricCard, r: Reading) {
        c.value.text = r.value
        c.value.textSize = 20f
        c.value.setTextColor(ui.p.ink)
        c.detail.removeAllViews()
        val details = r.details.ifEmpty {
            val sources = r.sources.map(a::sourceLabel).distinct().sorted()
            if (sources.isEmpty()) emptyList() else listOf("来源  " + sources.joinToString("、"))
        }
        details.forEach { c.detail.addView(ui.small(it, ui.p.ink2), ui.params(4)) }
    }
}

// ---- 应用使用 ----------------------------------------------------------------

class AppsPage(a: MainActivity) : Page(a) {
    private class Usage(val screen: Long, val count: Int, val list: List<Pair<String, Long>>)

    override fun show() {
        body.removeAllViews()
        body.addView(dateNav())
        val card = ui.card("应用使用")
        body.addView(card, ui.params(14))
        val reader = UsageReader(a)
        if (!reader.granted()) {
            card.addView(ui.small("还没打开「使用情况访问权限」，打开后这里会显示每个 App 用了多久。"), ui.params(6))
            card.addView(ui.button("去打开", Ui.Btn.PRIMARY) { SettingsPage.openUsage(a) }, ui.wrap().apply { topMargin = ui.dp(10) })
            return
        }
        card.addView(ui.small("正在读取"), ui.params(6))
        note("只记 App 的名字和用了多久，读不到 App 里面的内容。系统只保留最近几天的明细。")
        val shown = a.day
        load({
            val zone = ZoneId.systemDefault()
            val start = shown.atStartOfDay(zone).toInstant().toEpochMilli()
            val end = minOf(shown.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli(), System.currentTimeMillis())
            val read = reader.read(start - 2 * 3600_000L, end)
            val per = HashMap<String, Long>()
            read.apps.forEach { s -> (minOf(s.end, end) - maxOf(s.start, start)).takeIf { it > 0 }?.let { per[s.pkg] = (per[s.pkg] ?: 0) + it } }
            val screen = read.screens.sumOf { maxOf(0L, minOf(it.end, end) - maxOf(it.start, start)) }
            Usage(screen, per.size, per.entries.sortedByDescending { it.value }.filter { it.value >= 60_000 }.take(20)
                .map { reader.label(it.key) to it.value })
        }) { u ->
            card.removeViews(1, card.childCount - 1)
            if (u.count == 0) {
                card.addView(ui.small("这一天没有使用记录。"), ui.params(6))
                return@load
            }
            card.addView(ui.text("亮屏 ${duration(u.screen)}", 20f), ui.params(4))
            card.addView(ui.small(if (u.list.isEmpty()) "用过 ${u.count} 个 App，每个都不到 1 分钟" else "用过 ${u.count} 个 App"), ui.params(2))
            val max = u.list.firstOrNull()?.second ?: 1L
            u.list.forEach { (name, ms) ->
                val r = ui.row()
                r.addView(ui.text(name, 15f, ui.p.ink2), ui.weight())
                r.addView(ui.text(duration(ms), 15f, ui.p.ink3))
                card.addView(r, ui.params(8))
                // 下面一道铅笔线，长短表示用了多久
                val bar = ui.row()
                val frac = (ms.toFloat() / max).coerceIn(0.04f, 1f)
                bar.addView(View(a).apply { background = SketchDrawable(ui.density, ui.p.ink3, SketchDrawable.Shape.LINE_BOTTOM, animate = false) },
                    LinearLayout.LayoutParams(0, ui.dp(10), frac))
                bar.addView(View(a), LinearLayout.LayoutParams(0, ui.dp(10), 1f - frac + 0.0001f))
                card.addView(bar)
            }
        }
    }
}

// ---- 设置 ----------------------------------------------------------------

class SettingsPage(a: MainActivity) : Page(a) {
    private var nameInput: EditText? = null

    override fun show() {
        body.removeAllViews()

        val me = ui.card("我")
        val r = ui.row()
        val avatar = AvatarView(a, ui)
        java.io.File(a.filesDir, "avatar.png").takeIf { it.exists() }?.let { avatar.set(android.graphics.BitmapFactory.decodeFile(it.path)) }
        r.addView(avatar, LinearLayout.LayoutParams(ui.dp(76), ui.dp(76)))
        r.addView(ui.button("换头像") { a.pickAvatar() }, ui.wrap(14))
        me.addView(r, ui.params(10))
        val name = ui.input("你的名字", nameInput?.text?.toString() ?: Sync.prefs(a).getString("my_name", "").orEmpty())
        nameInput = name
        me.addView(name, ui.params(12))
        me.addView(ui.button("保存名字", Ui.Btn.PRIMARY) {
            Sync.prefs(a).edit().putString("my_name", name.text.toString().trim().take(20)).apply()
            nameInput = null
            a.refreshProfile()
            ui.say("保存好了", "顶上会显示「${a.profileName()}」。")
        }, ui.wrap().apply { topMargin = ui.dp(10) })
        me.addView(ui.small("头像和名字只存在这台手机上，不会传给电脑。"), ui.params(8))
        body.addView(me)

        val prep = ui.card("权限")
        val reader = a.healthReader
        val health = if (reader == null) 0 else Metric.entries.count { Sync.granted(a, it.readPermission) }
        row(prep, "健康数据", when {
            reader == null -> "这台手机用不了系统的健康数据"
            health == Metric.entries.size -> "已授权（步数、热量、心率、睡眠）"
            else -> "已授权 $health / ${Metric.entries.size} 项"
        }, health == Metric.entries.size, when {
            reader == null -> null
            health < Metric.entries.size -> "去授权" to {
                val missing = Metric.entries.filterNot { Sync.granted(a, it.readPermission) }.map { it.readPermission } + Sync.BG_HEALTH
                a.requestPermissions(missing.toTypedArray(), HEALTH_REQUEST)
            }
            else -> "管理" to {
                try {
                    a.startActivity(Intent(HealthConnectManager.ACTION_MANAGE_HEALTH_PERMISSIONS).putExtra(Intent.EXTRA_PACKAGE_NAME, a.packageName))
                } catch (_: ActivityNotFoundException) {
                }
            }
        })
        val usage = UsageReader(a).granted()
        row(prep, "应用使用情况", if (usage) "已打开" else "还没打开：在列表里找到 AwyRead，打开开关", usage,
            if (usage) null else "去打开" to { openUsage(a) })
        val bg = Sync.granted(a, Sync.BG_HEALTH)
        row(prep, "后台读取健康数据", if (bg) "已允许" else "没允许时，只有打开这个 App 才读健康数据", bg,
            if (bg || reader == null) null else "去授权" to { a.requestPermissions(arrayOf(Sync.BG_HEALTH), HEALTH_REQUEST) })
        val power = a.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(a.packageName)
        row(prep, "允许后台运行",
            if (power) "已不受省电限制。ColorOS 还要在「应用详情 → 耗电管理」里允许后台运行和自启动"
            else "手机省电时会把它关掉，定时读取就停了", power, "去设置" to { openPower(power) })
        val last = Sync.prefs(a).getLong("last_collect", 0)
        prep.addView(ui.small("后台大约每小时读一次" + if (last > 0) "，上次 ${a.time(last)}" else ""), ui.params(12))
        body.addView(prep, ui.params(14))

        val about = ui.card("关于")
        about.addView(ui.text("AwyRead ${a.versionName()}", 16f), ui.params(6))
        about.addView(ui.small("作者 GitHub：$AUTHOR"), ui.params(2))
        val buttons = ui.row()
        buttons.addView(ui.button("检查更新") { a.checkUpdate() })
        buttons.addView(ui.button("数据怎么用") { a.startActivity(Intent(a, PrivacyActivity::class.java)) }, ui.wrap(10))
        about.addView(buttons, ui.params(10))
        body.addView(about, ui.params(14))
    }

    private fun row(card: LinearLayout, title: String, status: String, ok: Boolean, action: Pair<String, () -> Unit>?) {
        val r = ui.row()
        r.addView(ui.dot(if (ok) ui.p.ok else ui.p.warm))
        val texts = ui.column()
        texts.addView(ui.text(title))
        texts.addView(ui.small(status))
        r.addView(texts, ui.weight())
        if (action != null) r.addView(ui.button(action.first) { action.second() }, ui.wrap(8))
        card.addView(r, ui.params(12))
    }

    private fun openPower(alreadyExempt: Boolean) {
        val details = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${a.packageName}"))
        val intent = if (alreadyExempt) details
        else Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${a.packageName}"))
        try {
            a.startActivity(intent)
        } catch (_: ActivityNotFoundException) {
            a.startActivity(details)
        }
    }

    companion object {
        fun openUsage(a: MainActivity) {
            try {
                a.startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS, Uri.parse("package:${a.packageName}")))
            } catch (_: ActivityNotFoundException) {
                a.startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
            }
        }
    }
}

