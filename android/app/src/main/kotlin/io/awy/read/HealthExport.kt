package io.awy.read

import android.health.connect.AggregateRecordsGroupedByDurationResponse
import android.health.connect.AggregateRecordsRequest
import android.health.connect.HealthConnectException
import android.health.connect.HealthConnectManager
import android.health.connect.ReadRecordsRequestUsingFilters
import android.health.connect.ReadRecordsResponse
import android.health.connect.TimeInstantRangeFilter
import android.health.connect.datatypes.HeartRateRecord
import android.health.connect.datatypes.SleepSessionRecord
import android.health.connect.datatypes.StepsRecord
import android.os.OutcomeReceiver
import java.time.Duration
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** 一小时的健康汇总。没有数据的项是 null。 */
data class HealthHour(val start: Instant, val steps: Long?, val hrMin: Long?, val hrAvg: Long?, val hrMax: Long?)

/** 一次睡眠：各阶段的分钟数；by 是写入这条记录的 App。 */
data class SleepItem(
    val start: Instant, val end: Instant, val deep: Long, val light: Long, val rem: Long, val awake: Long, val by: String
)

/**
 * 给「传到电脑」用的健康数据：按小时的步数和心率（最低 / 平均 / 最高），加上睡眠。
 * 按小时汇总用的是系统自带的汇总（手机和手表同时记步时，系统会去重，不会重复相加）。
 * 这里是同步调用（会等结果），只能在后台线程里用。
 */
class HealthExport(private val manager: HealthConnectManager, private val label: (String) -> String) : AutoCloseable {
    private val executor = Executors.newSingleThreadExecutor()

    override fun close() = executor.shutdown()

    private fun <T> await(block: (OutcomeReceiver<T, HealthConnectException>) -> Unit): T {
        val latch = CountDownLatch(1)
        var value: T? = null
        var error: Throwable? = null
        block(object : OutcomeReceiver<T, HealthConnectException> {
            override fun onResult(result: T) {
                value = result
                latch.countDown()
            }

            override fun onError(e: HealthConnectException) {
                error = e
                latch.countDown()
            }
        })
        if (!latch.await(60, TimeUnit.SECONDS)) throw IllegalStateException("Health Connect 没有回应")
        error?.let { throw it }
        @Suppress("UNCHECKED_CAST")
        return value as T
    }

    /** steps / heart：有哪项读取权限（没权限的项不能放进请求，否则整个请求都会失败）。 */
    fun hours(from: Instant, to: Instant, steps: Boolean, heart: Boolean): List<HealthHour> {
        val range = TimeInstantRangeFilter.Builder().setStartTime(from).setEndTime(to).build()
        val builder = AggregateRecordsRequest.Builder<Long>(range)
        if (steps) builder.addAggregationType(StepsRecord.STEPS_COUNT_TOTAL)
        if (heart) {
            builder.addAggregationType(HeartRateRecord.BPM_MIN)
            builder.addAggregationType(HeartRateRecord.BPM_AVG)
            builder.addAggregationType(HeartRateRecord.BPM_MAX)
        }
        val request = builder.build()
        val groups: List<AggregateRecordsGroupedByDurationResponse<Long>> = await { r ->
            manager.aggregateGroupByDuration(request, Duration.ofHours(1), executor, r)
        }
        return groups.mapNotNull { g ->
            val count = if (steps) g.get(StepsRecord.STEPS_COUNT_TOTAL)?.takeIf { it > 0 } else null
            val avg = if (heart) g.get(HeartRateRecord.BPM_AVG) else null
            if (count == null && avg == null) null
            else HealthHour(g.startTime, count, if (heart) g.get(HeartRateRecord.BPM_MIN) else null, avg,
                if (heart) g.get(HeartRateRecord.BPM_MAX) else null)
        }
    }

    fun sleep(from: Instant, to: Instant): List<SleepItem> {
        val range = TimeInstantRangeFilter.Builder().setStartTime(from).setEndTime(to).build()
        val out = mutableListOf<SleepItem>()
        var token: Long? = null
        do {
            val b = ReadRecordsRequestUsingFilters.Builder(SleepSessionRecord::class.java).setTimeRangeFilter(range).setPageSize(200)
            token?.let { b.setPageToken(it) }
            val page: ReadRecordsResponse<SleepSessionRecord> = await { r -> manager.readRecords(b.build(), executor, r) }
            for (s in page.records) {
                var deep = 0L
                var light = 0L
                var rem = 0L
                var awake = 0L
                for (st in s.stages) {
                    val min = Duration.between(st.startTime, st.endTime).toMinutes()
                    when (st.type) {
                        SleepSessionRecord.StageType.STAGE_TYPE_SLEEPING_DEEP -> deep += min
                        SleepSessionRecord.StageType.STAGE_TYPE_SLEEPING_LIGHT -> light += min
                        SleepSessionRecord.StageType.STAGE_TYPE_SLEEPING_REM -> rem += min
                        SleepSessionRecord.StageType.STAGE_TYPE_AWAKE,
                        SleepSessionRecord.StageType.STAGE_TYPE_AWAKE_IN_BED,
                        SleepSessionRecord.StageType.STAGE_TYPE_AWAKE_OUT_OF_BED -> awake += min
                    }
                }
                out += SleepItem(s.startTime, s.endTime, deep, light, rem, awake, label(s.metadata.dataOrigin.packageName))
            }
            token = page.nextPageToken.takeIf { it != -1L }
        } while (token != null)
        return out
    }
}
