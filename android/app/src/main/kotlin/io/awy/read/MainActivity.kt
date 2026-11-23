package io.awy.read

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.health.connect.HealthConnectManager
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors

const val HEALTH_REQUEST = 1
const val LOCAL_NETWORK_REQUEST = 2
const val AVATAR_REQUEST = 3
const val LOCAL_NETWORK = "android.permission.ACCESS_LOCAL_NETWORK"
const val AUTHOR = "The-Dark-Iceberg"

/** 时长写成「1 小时 5 分」「12 分」「不到 1 分」。 */
fun duration(millis: Long): String {
    val minutes = (millis + 30_000) / 60_000
    if (minutes < 1) return "不到 1 分"
    if (minutes < 60) return "$minutes 分"
    val h = minutes / 60
    val m = minutes % 60
    return if (m == 0L) "$h 小时" else "$h 小时 $m 分"
}

/**
 * 主界面（按用户画的版面，决定 0014 补充）：
 * 顶栏：左边自己的头像和名字（点了去「设置」改），右边小黑猫（作者 GitHub、版本、检查更新）和「+」（功能选择）。
 * 中间：当前页。底栏：主页 / 配对传输 / 健康 / 应用 / 设置。
 */
class MainActivity : Activity() {
    lateinit var ui: Ui
    var day: LocalDate = LocalDate.now()
    val worker = Executors.newSingleThreadExecutor()
    internal var healthReader: HealthReader? = null
    var version = 0          // 换页 / 离开时加一：之前发出去的读取回来了就不再往界面上填
    var syncing = false
    var current = "home"

    private lateinit var content: FrameLayout
    private lateinit var avatar: AvatarView
    private lateinit var nameView: TextView
    private val pages = LinkedHashMap<String, Page>()
    private val tabs = mutableMapOf<String, Tab>()

    private class Tab(val icon: IconDrawable, val ring: View, val label: TextView)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ui = Ui(this)
        day = savedInstanceState?.getString("day")?.let(LocalDate::parse) ?: LocalDate.now()
        current = savedInstanceState?.getString("tab") ?: "home"
        healthReader = getSystemService(HealthConnectManager::class.java)?.let {
            HealthReader(applicationContext, it, healthCallbacks, ::sourceLabel)
        }
        pages["home"] = HomePage(this)
        pages["pc"] = PcPage(this)
        pages["health"] = HealthPage(this)
        pages["apps"] = AppsPage(this)
        pages["settings"] = SettingsPage(this)

        val root = ui.column()
        root.addView(topBar(), LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        content = FrameLayout(this)
        root.addView(content, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        root.addView(bottomBar(), LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        window.setDecorFitsSystemWindows(false)
        window.decorView.background = PaperDrawable(ui.p, ui.density)
        root.setOnApplyWindowInsetsListener { v, insets ->
            val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            val ime = insets.getInsets(WindowInsets.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
            WindowInsets.CONSUMED
        }
        setContentView(root)
        val light = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
        window.insetsController?.setSystemBarsAppearance(if (ui.p.dark) 0 else light, light)
        refreshProfile()
        show(current)
        root.post { ui.startDrawing() }
        SyncJob.schedule(this)
    }

    override fun onResume() {
        super.onResume()
        refreshProfile()
        pages[current]?.show()
        // 打开 App 时顺手读一次、传一次（离上次超过 5 分钟才读）
        if (System.currentTimeMillis() - Sync.prefs(this).getLong("last_collect", 0) > 5 * 60_000) syncNow(quiet = true)
    }

    override fun onPause() {
        ++version
        super.onPause()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString("day", day.toString())
        outState.putString("tab", current)
    }

    // ---- 顶栏 ----------------------------------------------------------------

    private fun topBar(): View = ui.row().apply {
        setPadding(ui.dp(14), ui.dp(6), ui.dp(8), ui.dp(8))
        background = ui.sketch(ui.p.ink, SketchDrawable.Shape.LINE_BOTTOM)
        avatar = AvatarView(this@MainActivity, ui)
        nameView = ui.text("", 19f)
        val me = ui.row().apply {
            isClickable = true
            setOnClickListener { show("settings") }
            contentDescription = "我的头像和名字，点了去设置里修改"
            addView(avatar, LinearLayout.LayoutParams(ui.dp(46), ui.dp(46)))
            addView(nameView, ui.wrap(10))
        }
        addView(me, ui.weight())
        addView(ui.iconButton("cat", "关于：作者、版本、检查更新") { aboutMenu(it) })
        addView(ui.iconButton("plus", "功能选择") { featureMenu(it) })
    }

    fun profileName(): String = Sync.prefs(this).getString("my_name", "").orEmpty().ifBlank { "我" }

    fun refreshProfile() {
        nameView.text = profileName()
        val f = File(filesDir, "avatar.png")
        avatar.set(if (f.exists()) BitmapFactory.decodeFile(f.path) else null)
    }

    private fun aboutMenu(anchor: View) = ui.popup(anchor, "关于", listOf(
        Triple("link", "作者 GitHub：$AUTHOR") { openUrl("https://github.com/$AUTHOR") },
        Triple("spark", "当前版本 ${versionName()}") { ui.say("AwyRead ${versionName()}", "一个时刻陪着你的AI · 手机端。\n把手机上的一天，带回你的电脑。") },
        Triple("download", "检查更新") { checkUpdate() },
    ))

    private fun featureMenu(anchor: View) {
        val later = { ui.say("还在准备中", "这里以后会放一些小工具，现在还没做好。") }
        ui.popup(anchor, "功能选择", listOf(
            Triple("box", "小工具箱（暂定）", later),
            Triple(null, "暂定", later),
            Triple(null, "暂定", later),
            Triple(null, "……", later),
        ))
    }

    fun versionName(): String = packageManager.getPackageInfo(packageName, 0).versionName ?: "?"

    fun openUrl(url: String) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (_: ActivityNotFoundException) {
            ui.say("打不开", "手机上没有能打开网页的 App。")
        }
    }

    /** 去 GitHub 的公开发布仓库看有没有新版本（和电脑端「检查更新」同一个仓库）。只在点按钮时联网。 */
    fun checkUpdate() {
        worker.execute {
            val (message, link) = Updater.check(versionName())
            runOnUiThread {
                if (link != null) ui.say("检查更新", message, "去下载" to { openUrl(link) }) else ui.say("检查更新", message)
            }
        }
    }

    // ---- 底栏和换页 ----------------------------------------------------------------

    private fun bottomBar(): View = ui.row().apply {
        setPadding(ui.dp(4), ui.dp(8), ui.dp(4), ui.dp(4))
        background = ui.sketch(ui.p.ink, SketchDrawable.Shape.LINE_TOP)
        listOf("home" to ("home" to "主页"), "pc" to ("transfer" to "配对传输"), "health" to ("heart" to "健康"),
            "apps" to ("grid" to "应用"), "settings" to ("gear" to "设置")).forEach { (key, v) ->
            val (iconName, label) = v
            val item = ui.column().apply {
                gravity = Gravity.CENTER_HORIZONTAL
                isClickable = true
                contentDescription = label
                setOnClickListener { show(key) }
            }
            val ring = FrameLayout(this@MainActivity)
            val icon = Icons.drawable(iconName, ui.p.ink3, ui.density)
            ring.addView(View(this@MainActivity).apply { background = icon }, FrameLayout.LayoutParams(ui.dp(26), ui.dp(26), Gravity.CENTER))
            item.addView(ring, LinearLayout.LayoutParams(ui.dp(46), ui.dp(46)))
            val text = ui.text(label, 12.5f, ui.p.ink3).apply { gravity = Gravity.CENTER }
            item.addView(text)
            tabs[key] = Tab(icon, ring, text)
            addView(item, ui.weight())
        }
    }

    fun show(tab: String) {
        val page = pages[tab] ?: return
        current = tab
        ++version
        content.removeAllViews()
        content.addView(page.view)
        page.view.scrollTo(0, 0)
        page.show()
        tabs.forEach { (k, t) ->
            val on = k == tab
            t.icon.setInk(if (on) ui.p.ink else ui.p.ink3)
            t.label.setTextColor(if (on) ui.p.ink else ui.p.ink3)
            t.ring.background = if (on) SketchDrawable(ui.density, ui.p.ink2, SketchDrawable.Shape.CIRCLE, animate = false) else null
        }
    }

    // ---- 同步 ----------------------------------------------------------------

    fun syncNow(quiet: Boolean, done: ((String) -> Unit)? = null) {
        if (syncing) return
        syncing = true
        if (!quiet) pages[current]?.show()
        worker.execute {
            val message = Sync.run(applicationContext, background = false)
            runOnUiThread {
                syncing = false
                done?.invoke(message)
                if (!isDestroyed && (current == "pc" || current == "home" || current == "settings")) pages[current]?.show()
            }
        }
    }

    // ---- 权限、选头像 ----------------------------------------------------------------

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, results)
        when (requestCode) {
            HEALTH_REQUEST -> pages[current]?.show()
            LOCAL_NETWORK_REQUEST -> (pages["pc"] as PcPage).afterLocalNetwork(Sync.granted(this, LOCAL_NETWORK))
        }
    }

    fun pickAvatar() {
        try {
            @Suppress("DEPRECATION")
            startActivityForResult(Intent(MediaStore.ACTION_PICK_IMAGES).setType("image/*"), AVATAR_REQUEST)
        } catch (_: ActivityNotFoundException) {
            @Suppress("DEPRECATION")
            startActivityForResult(Intent(Intent.ACTION_GET_CONTENT).setType("image/*"), AVATAR_REQUEST)
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        val uri = data?.data
        if (requestCode != AVATAR_REQUEST || resultCode != RESULT_OK || uri == null) return
        worker.execute {
            val ok = try {
                saveAvatar(uri)
                true
            } catch (e: Exception) {
                false
            }
            runOnUiThread {
                refreshProfile()
                if (current == "settings") pages[current]?.show()
                if (!ok) ui.say("换头像失败", "这张图读不出来，换一张试试。")
            }
        }
    }

    /** 头像：从中间裁成正方形，缩到 320 像素，存在 App 私有目录（不上传）。 */
    private fun saveAvatar(uri: Uri) {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        var sample = 1
        while (minOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= 320) sample *= 2
        val full = contentResolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
        } ?: throw IOException("读不出图片")
        val side = minOf(full.width, full.height)
        val square = Bitmap.createBitmap(full, (full.width - side) / 2, (full.height - side) / 2, side, side)
        val small = Bitmap.createScaledBitmap(square, 320, 320, true)
        File(filesDir, "avatar.png").outputStream().use { small.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    fun sourceLabel(origin: String): String = UsageReader(this).label(origin)

    fun time(millis: Long): String {
        val t = Instant.ofEpochMilli(millis).atZone(ZoneId.systemDefault())
        val pattern = if (t.toLocalDate() == LocalDate.now()) "HH:mm" else "M月d日 HH:mm"
        return t.format(DateTimeFormatter.ofPattern(pattern))
    }

    companion object {
        private val healthCallbacks = Executors.newSingleThreadExecutor()
    }
}

/**
 * 检查更新：看公开仓库 Releases 里的手机版。版本号从附件名 AwyRead-<版本>.apk 里读
 * （发布的标签是电脑版的版本号，和手机版不一样，不能拿标签比）。取所有发布里版本最大的那个。
 */
object Updater {
    private const val REPO = "$AUTHOR/always-with-you"
    private val APK = Regex("^AwyRead-(\\d+\\.\\d+\\.\\d+)\\.apk$")

    private fun parts(v: String) = Regex("\\d+").findAll(v).map { it.value.toInt() }.toList()

    fun newer(remote: String, local: String): Boolean {
        val a = parts(remote)
        val b = parts(local)
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(i) { 0 }
            val y = b.getOrElse(i) { 0 }
            if (x != y) return x > y
        }
        return false
    }

    fun check(current: String): Pair<String, String?> = try {
        val c = URL("https://api.github.com/repos/$REPO/releases?per_page=10").openConnection() as HttpURLConnection
        c.connectTimeout = 8000
        c.readTimeout = 10000
        c.setRequestProperty("Accept", "application/vnd.github+json")
        when (val code = c.responseCode) {
            404 -> "找不到发布页（$REPO），过一会儿再试。" to null
            200 -> {
                val list = org.json.JSONArray(c.inputStream.bufferedReader().use { it.readText() })
                // 每个正式发布里找 AwyRead-<版本>.apk，取版本最大的
                var best: Pair<String, String>? = null
                for (r in (0 until list.length()).map { list.getJSONObject(it) }) {
                    if (r.optBoolean("draft")) continue
                    val assets = r.optJSONArray("assets") ?: continue
                    for (a in (0 until assets.length()).map { assets.getJSONObject(it) }) {
                        val v = APK.find(a.optString("name"))?.groupValues?.get(1) ?: continue
                        if (best == null || newer(v, best.first)) best = v to a.optString("browser_download_url")
                    }
                }
                val found = best
                when {
                    found == null -> "发布页里还没有手机版。" to null
                    newer(found.first, current) -> "有新版本 ${found.first}（现在是 $current）。" to found.second
                    else -> "已经是最新版本（$current）。" to null
                }
            }
            else -> "检查失败（GitHub 返回 $code），过一会儿再试。" to null
        }
    } catch (e: IOException) {
        "连不上 GitHub：${e.message ?: "网络不通"}" to null
    } catch (e: org.json.JSONException) {
        "GitHub 返回的内容看不懂。" to null
    }
}

/** 系统设置里「健康数据使用说明」点进来的页面。 */
class PrivacyActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val ui = Ui(this)
        val page = ui.column().apply { setPadding(ui.dp(20), ui.dp(18), ui.dp(20), ui.dp(28)) }
        page.addView(ui.text(getString(R.string.privacy_title), 26f))
        page.addView(ui.text(getString(R.string.privacy_body), 16f, ui.p.ink2), ui.params(12))
        page.addView(ui.button(getString(R.string.close), Ui.Btn.PRIMARY) { finish() }, ui.params(20))
        window.setDecorFitsSystemWindows(false)
        window.decorView.background = PaperDrawable(ui.p, ui.density)
        val scroll = ScrollView(this).apply {
            isFillViewport = true
            addView(page)
            setOnApplyWindowInsetsListener { v, insets ->
                val safe = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                v.setPadding(safe.left, safe.top, safe.right, safe.bottom)
                WindowInsets.CONSUMED
            }
        }
        setContentView(scroll)
        page.post { ui.startDrawing() }
    }
}
