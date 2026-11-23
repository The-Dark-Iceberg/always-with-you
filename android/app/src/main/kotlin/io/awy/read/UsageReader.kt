package io.awy.read

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Process

/** 一段使用：某个 App 在前台从 start 到 end（毫秒）。closed = false 表示读的时候还在用。 */
data class AppSession(val pkg: String, val start: Long, val end: Long, val closed: Boolean = true) {
    val millis get() = end - start
}

/** 一段亮屏。 */
data class ScreenSession(val start: Long, val end: Long, val closed: Boolean = true)

class UsageDay(val apps: List<AppSession>, val screens: List<ScreenSession>)

/**
 * 应用使用情况（系统「使用情况访问权限」）。
 * 系统给的是「某个界面到前台 / 离开前台」「亮屏 / 灭屏」这样一条条事件，这里把它们拼成一段段使用。
 * 只读 App 的包名和时间，读不到 App 里面的内容。
 */
class UsageReader(private val context: Context) {
    private val usm = context.getSystemService(UsageStatsManager::class.java)

    fun granted(): Boolean {
        val ops = context.getSystemService(AppOpsManager::class.java)
        val mode = ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName)
        return mode == AppOpsManager.MODE_ALLOWED
    }

    /**
     * 不算的：桌面（启动器）、本 App 自己、系统界面（下拉栏等）。
     * 「设置」等 App 里也有一个备用桌面（开机时用），它们自己有桌面图标，不能当成桌面——
     * 所以只把「能当桌面、但自己没有桌面图标」的算作桌面。
     */
    private fun ignored(): Set<String> {
        val pm = context.packageManager
        val flags = PackageManager.ResolveInfoFlags.of(0)
        val homes = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), flags)
            .map { it.activityInfo.packageName }.toSet()
        val apps = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), flags)
            .map { it.activityInfo.packageName }.toSet()
        return (homes - apps) + context.packageName + "com.android.systemui" + "android"
    }

    /** 读 [from, to) 之间的使用片段。同一个 App 间隔不到 30 秒的合并成一段，短于 5 秒的不算。 */
    fun read(from: Long, to: Long): UsageDay {
        val skip = ignored()
        val events = usm.queryEvents(from, to) ?: return UsageDay(emptyList(), emptyList())
        val open = LinkedHashMap<String, Long>()
        val apps = mutableListOf<AppSession>()
        val screens = mutableListOf<ScreenSession>()
        var screenOn: Long? = null
        val e = UsageEvents.Event()
        fun close(pkg: String, at: Long) {
            val start = open.remove(pkg) ?: return
            if (at > start) apps += AppSession(pkg, start, at)
        }
        fun closeAll(at: Long) = open.keys.toList().forEach { close(it, at) }
        while (events.hasNextEvent()) {
            events.getNextEvent(e)
            val at = e.timeStamp
            when (e.eventType) {
                UsageEvents.Event.ACTIVITY_RESUMED -> {
                    if (e.packageName in skip) {
                        closeAll(at)   // 回到桌面 = 前面的 App 不在用了
                    } else if (e.packageName !in open) {
                        closeAll(at)   // 一次只算一个前台 App（分屏很少见，按后打开的算）
                        open[e.packageName] = at
                    }
                }
                UsageEvents.Event.ACTIVITY_PAUSED, UsageEvents.Event.ACTIVITY_STOPPED -> close(e.packageName, at)
                UsageEvents.Event.SCREEN_INTERACTIVE -> if (screenOn == null) screenOn = at
                UsageEvents.Event.SCREEN_NON_INTERACTIVE, UsageEvents.Event.DEVICE_SHUTDOWN -> {
                    closeAll(at)
                    screenOn?.let { if (at > it) screens += ScreenSession(it, at) }
                    screenOn = null
                }
            }
        }
        open.forEach { (pkg, start) -> if (to > start) apps += AppSession(pkg, start, to, closed = false) }
        screenOn?.let { if (to > it) screens += ScreenSession(it, to, closed = false) }
        return UsageDay(merge(apps.sortedBy { it.start }), screens)
    }

    private fun merge(items: List<AppSession>): List<AppSession> {
        val out = mutableListOf<AppSession>()
        for (s in items) {
            val last = out.lastOrNull()
            if (last != null && last.pkg == s.pkg && s.start - last.end <= 30_000) {
                out[out.size - 1] = AppSession(s.pkg, last.start, maxOf(last.end, s.end), s.closed)
            } else {
                out += s
            }
        }
        return out.filter { it.millis >= 5_000 }
    }

    /** 包名 → App 名字。系统健康中心自己记的（手机自带计步）包名是 com.android.healthconnect.phone.一串编号。 */
    fun label(pkg: String): String = if (pkg.startsWith("com.android.healthconnect.phone")) "手机自带计步" else try {
        val pm = context.packageManager
        pm.getApplicationLabel(pm.getApplicationInfo(pkg, PackageManager.ApplicationInfoFlags.of(0))).toString()
    } catch (_: PackageManager.NameNotFoundException) {
        pkg
    }
}
