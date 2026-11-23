package io.awy.read

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.health.connect.HealthConnectManager
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.temporal.ChronoUnit

/** 待上传队列：App 私有目录里的 queue.jsonl，一行一条。传成功才删；最多留 5 万条（太多时丢最旧的）。 */
class Queue(context: Context) {
    private val file = File(context.filesDir, "queue.jsonl")

    @Synchronized
    fun add(items: List<JSONObject>) {
        if (items.isEmpty()) return
        file.appendText(items.joinToString("\n", postfix = "\n") { it.toString() })
        val lines = lines()
        if (lines.size > MAX) write(lines.takeLast(MAX))
    }

    @Synchronized
    fun peek(n: Int): List<String> = lines().take(n)

    @Synchronized
    fun drop(n: Int) = write(lines().drop(n))

    @Synchronized
    fun size(): Int = lines().size

    private fun lines(): List<String> = if (file.exists()) file.readLines().filter { it.isNotBlank() } else emptyList()

    private fun write(lines: List<String>) {
        val tmp = File(file.path + ".tmp")
        tmp.writeText(if (lines.isEmpty()) "" else lines.joinToString("\n", postfix = "\n"))
        tmp.renameTo(file)
    }

    companion object {
        private const val MAX = 50_000
    }
}

/**
 * 读新数据 → 放进待上传队列 → （已配对、连着 Wi-Fi 时）传给电脑。
 * 后台每小时跑一次（SyncJob），打开 App 或点「立即同步」时也会跑。
 *
 * 发出去的每条都有一个「键」（比如 app|包名|开始时间）。同一个键内容没变就不重发；
 * 变了（比如手表晚同步、某个小时的步数变多了）就再发一次，电脑以最新的为准。
 */
object Sync {
    private const val TAG = "AwyRead"
    const val BG_HEALTH = "android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND"
    private val lock = Any()

    fun prefs(context: Context): SharedPreferences = context.getSharedPreferences("awy", Context.MODE_PRIVATE)

    fun iso(millis: Long): String =
        OffsetDateTime.ofInstant(Instant.ofEpochMilli(millis), ZoneId.systemDefault()).truncatedTo(ChronoUnit.SECONDS).toString()

    fun iso(instant: Instant): String = iso(instant.toEpochMilli())

    fun granted(context: Context, permission: String) =
        context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    /** background：后台定时任务调用时为 true，这时只有给了「后台读取健康数据」才读健康数据。 */
    fun run(context: Context, background: Boolean): String = synchronized(lock) {
        val queue = Queue(context)
        try {
            queue.add(dedup(context, collectUsage(context)))
        } catch (e: Exception) {
            Log.w(TAG, "读应用使用情况失败", e)
        }
        if (!background || granted(context, BG_HEALTH)) {
            try {
                queue.add(dedup(context, collectHealth(context)))
            } catch (e: Exception) {
                Log.w(TAG, "读健康数据失败", e)
            }
        }
        prefs(context).edit().putLong("last_collect", System.currentTimeMillis()).apply()
        val message = try {
            PcLink(context).upload(queue)
        } catch (e: Exception) {
            Log.w(TAG, "上传失败", e)
            "上传出错：${e.message}"
        }
        if (PcLink(context).paired) record(context, message, background)   // 没配对时不记（每次打开都是同一句，没意义）
        return message
    }

    /** 「配对传输」页的传输记录：每次同步的时间和结果，只留最近 20 条，只存在手机上。 */
    private fun record(context: Context, message: String, background: Boolean) {
        val p = prefs(context)
        val list = try {
            org.json.JSONArray(p.getString("history", "[]"))
        } catch (_: Exception) {
            org.json.JSONArray()
        }
        val out = org.json.JSONArray()
        out.put(JSONObject().put("t", System.currentTimeMillis()).put("m", message).put("bg", background))
        for (i in 0 until minOf(list.length(), 19)) out.put(list.get(i))
        p.edit().putString("history", out.toString()).apply()
    }

    fun history(context: Context): List<Triple<Long, String, Boolean>> = try {
        val a = org.json.JSONArray(prefs(context).getString("history", "[]"))
        (0 until a.length()).map { a.getJSONObject(it) }.map { Triple(it.getLong("t"), it.getString("m"), it.optBoolean("bg")) }
            .filter { it.second != "还没和电脑配对" }   // 0.3.0 之前没配对时也记了这句
    } catch (_: Exception) {
        emptyList()
    }

    fun pending(context: Context): Int {
        val inflight = File(context.filesDir, "inflight.json")
        val extra = if (inflight.exists()) try {
            JSONObject(inflight.readText()).getJSONArray("events").length()
        } catch (_: Exception) {
            0
        } else 0
        return Queue(context).size() + extra
    }

    // ---- 应用使用 ----------------------------------------------------------------

    private fun collectUsage(context: Context): List<Pair<String, JSONObject>> {
        val reader = UsageReader(context)
        if (!reader.granted()) return emptyList()
        val p = prefs(context)
        val now = System.currentTimeMillis()
        val floor = now - Duration.ofDays(2).toMillis()   // 系统只留几天的明细，最多往回读两天
        val firstTime = LocalDate.now().minusDays(1).atStartOfDay(ZoneId.systemDefault()).toInstant().toEpochMilli()
        val cursor = maxOf(p.getLong("usage_cursor", firstTime), floor)
        val day = reader.read(cursor - 1000, now)
        val out = mutableListOf<Pair<String, JSONObject>>()
        for (a in day.apps) {
            if (!a.closed || a.start < cursor - 1000) continue
            out += "app|${a.pkg}|${a.start / 1000}" to JSONObject()
                .put("k", "app").put("pkg", a.pkg).put("app", reader.label(a.pkg))
                .put("start", iso(a.start)).put("end", iso(a.end))
        }
        for (s in day.screens) {
            if (!s.closed || s.start < cursor - 1000) continue
            out += "screen|${s.start / 1000}" to JSONObject().put("k", "screen").put("start", iso(s.start)).put("end", iso(s.end))
        }
        // 还没结束的那段（正在用的 App、还亮着的屏幕）下次再发：游标停在它开始的地方
        val openStarts = day.apps.filter { !it.closed }.map { it.start } + day.screens.filter { !it.closed }.map { it.start }
        p.edit().putLong("usage_cursor", openStarts.minOrNull() ?: now).apply()
        return out
    }

    // ---- 健康 ----------------------------------------------------------------

    private fun collectHealth(context: Context): List<Pair<String, JSONObject>> {
        val manager = context.getSystemService(HealthConnectManager::class.java) ?: return emptyList()
        val steps = granted(context, Metric.STEPS.readPermission)
        val heart = granted(context, Metric.HEART.readPermission)
        val sleep = granted(context, Metric.SLEEP.readPermission)
        if (!steps && !heart && !sleep) return emptyList()
        val reader = UsageReader(context)
        HealthExport(manager, reader::label).use { export -> return healthItems(export, steps, heart, sleep) }
    }

    private fun healthItems(export: HealthExport, steps: Boolean, heart: Boolean, sleep: Boolean): List<Pair<String, JSONObject>> {
        val to = Instant.now()
        val from = to.minus(Duration.ofHours(48)).truncatedTo(ChronoUnit.HOURS)   // 手表常常晚一会儿才同步，重读最近两天
        val out = mutableListOf<Pair<String, JSONObject>>()
        if (steps || heart) {
            for (h in export.hours(from, to, steps, heart)) {
                val j = JSONObject().put("k", "hour").put("start", iso(h.start))
                h.steps?.let { j.put("steps", it) }
                h.hrMin?.let { j.put("hr_min", it) }
                h.hrAvg?.let { j.put("hr_avg", it) }
                h.hrMax?.let { j.put("hr_max", it) }
                out += "hour|${h.start.epochSecond}" to j
            }
        }
        if (sleep) {
            for (s in export.sleep(from.minus(Duration.ofHours(12)), to)) {
                out += "sleep|${s.start.epochSecond}" to JSONObject().put("k", "sleep")
                    .put("start", iso(s.start)).put("end", iso(s.end))
                    .put("deep", s.deep).put("light", s.light).put("rem", s.rem).put("awake", s.awake).put("by", s.by)
            }
        }
        return out
    }

    // ---- 不重复发 ----------------------------------------------------------------

    private fun dedup(context: Context, items: List<Pair<String, JSONObject>>): List<JSONObject> {
        if (items.isEmpty()) return emptyList()
        val file = File(context.filesDir, "sent.json")
        val sent = try {
            JSONObject(file.readText())
        } catch (_: Exception) {
            JSONObject()
        }
        val now = System.currentTimeMillis() / 1000
        val out = items.filter { (key, item) ->
            val hash = item.toString().hashCode().toString()
            if (sent.optString(key).substringBefore('|') == hash) false
            else {
                sent.put(key, "$hash|$now")
                true
            }
        }.map { it.second }
        // 五天前记下的键用不着了（再早的数据不会重读），删掉免得越来越大
        val old = sent.keys().asSequence().filter { (sent.optString(it).substringAfter('|').toLongOrNull() ?: 0) < now - 5 * 86400 }.toList()
        old.forEach { sent.remove(it) }
        val tmp = File(file.path + ".tmp")
        tmp.writeText(sent.toString())
        tmp.renameTo(file)
        return out
    }
}

/** 后台定时任务：大约每小时一次（系统会根据电量适当推迟）。 */
class SyncJob : JobService() {
    override fun onStartJob(params: JobParameters): Boolean {
        Thread {
            try {
                Sync.run(applicationContext, background = true)
            } finally {
                jobFinished(params, false)
            }
        }.start()
        return true
    }

    override fun onStopJob(params: JobParameters) = true

    companion object {
        private const val ID = 1

        fun schedule(context: Context) {
            val js = context.getSystemService(JobScheduler::class.java)
            if (js.getPendingJob(ID) != null) return
            js.schedule(
                JobInfo.Builder(ID, ComponentName(context, SyncJob::class.java))
                    .setPeriodic(Duration.ofHours(1).toMillis(), Duration.ofMinutes(15).toMillis())
                    .setPersisted(true)   // 重启手机后继续
                    .build()
            )
        }
    }
}
