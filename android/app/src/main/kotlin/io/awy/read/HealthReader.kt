package io.awy.read

import android.content.Context
import android.health.connect.AggregateRecordsRequest
import android.health.connect.AggregateRecordsResponse
import android.health.connect.HealthConnectException
import android.health.connect.HealthConnectManager
import android.health.connect.ReadRecordsRequestUsingFilters
import android.health.connect.ReadRecordsResponse
import android.health.connect.TimeInstantRangeFilter
import android.health.connect.datatypes.AggregationType
import android.health.connect.datatypes.HeartRateRecord
import android.health.connect.datatypes.IntervalRecord
import android.health.connect.datatypes.Record
import android.health.connect.datatypes.SleepSessionRecord
import android.health.connect.datatypes.StepsRecord
import android.health.connect.datatypes.TotalCaloriesBurnedRecord
import android.os.OutcomeReceiver
import java.text.NumberFormat
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executor
import kotlin.math.roundToLong

enum class Metric(val title: Int, permission: String) {
    STEPS(R.string.steps, "READ_STEPS"),
    CALORIES(R.string.calories, "READ_TOTAL_CALORIES_BURNED"),
    HEART(R.string.heart_rate, "READ_HEART_RATE"),
    SLEEP(R.string.sleep, "READ_SLEEP");

    val readPermission = "android.permission.health.$permission"
}

data class Reading(
    val value: String,
    val sources: Set<String>,
    val details: List<String> = emptyList()
)

internal class HealthReader(
    private val context: Context,
    private val manager: HealthConnectManager,
    private val executor: Executor,
    private val sourceLabel: (String) -> String
) {
    fun read(metric: Metric, day: LocalDate, zone: ZoneId, done: (Result<Reading?>) -> Unit) {
        val start = day.atStartOfDay(zone).toInstant()
        val end = day.plusDays(1).atStartOfDay(zone).toInstant()
        val range = range(start, end)
        when (metric) {
            Metric.STEPS -> readSteps(range, start, end, done)
            Metric.CALORIES -> readRecords(TotalCaloriesBurnedRecord::class.java, range, done) { records ->
                // The system aggregate can fill gaps with estimated basal energy.
                // Show calories actually recorded in Health Connect, by source.
                val format = NumberFormat.getNumberInstance().apply { maximumFractionDigits = 1 }
                summarizeActivity(records, start, end, { it.energy.inCalories / 1000.0 }) {
                    context.getString(R.string.calorie_value, format.format(it))
                }
            }
            Metric.HEART -> readRecords(HeartRateRecord::class.java, range, done) { records ->
                summarizeHeart(records, start, end, zone)
            }
            Metric.SLEEP -> {
                // Look on both sides of midnight and assign a session to its wake-up date.
                val sleepRange = range(day.minusDays(1).atStartOfDay(zone).toInstant(), end)
                readRecords(SleepSessionRecord::class.java, sleepRange, done) { records ->
                    summarizeSleep(records, start, end, zone)
                }
            }
        }
    }

    private fun range(start: Instant, end: Instant) = TimeInstantRangeFilter.Builder()
        .setStartTime(start)
        .setEndTime(end)
        .build()

    private fun readSteps(
        range: TimeInstantRangeFilter,
        start: Instant,
        end: Instant,
        done: (Result<Reading?>) -> Unit
    ) {
        fun format(value: Long) = context.getString(R.string.step_value, NumberFormat.getIntegerInstance().format(value))
        readRecords(StepsRecord::class.java, range, { sourceResult ->
            aggregate(StepsRecord.STEPS_COUNT_TOTAL, range, { aggregateResult ->
                val bySource = sourceResult.getOrNull()
                val total = aggregateResult.getOrNull()
                when {
                    total != null && bySource != null -> done(Result.success(total.copy(
                        details = bySource.details.ifEmpty {
                            bySource.sources.map { "${sourceLabel(it)} · ${bySource.value}" }
                        }
                    )))
                    total != null -> done(aggregateResult)
                    bySource != null || sourceResult.isFailure -> done(sourceResult)
                    else -> done(aggregateResult)
                }
            }) { context.getString(R.string.system_step_total, format(it)) }
        }) { records ->
            summarizeActivity(records, start, end, { it.count.toDouble() }) { format(it.roundToLong()) }
        }
    }

    private fun <T : IntervalRecord> summarizeActivity(
        records: List<T>,
        start: Instant,
        end: Instant,
        value: (T) -> Double,
        format: (Double) -> String
    ): Reading? {
        // Clip intervals to the selected day, including days with a daylight-saving transition.
        val totals = records.mapNotNull { record ->
            val overlapStart = maxOf(start, record.startTime)
            val overlapEnd = minOf(end, record.endTime)
            if (overlapEnd < overlapStart || overlapStart >= end) return@mapNotNull null
            val interval = Duration.between(record.startTime, record.endTime).toMillis()
            val overlap = Duration.between(overlapStart, overlapEnd).toMillis()
            if (overlap == 0L && interval != 0L) return@mapNotNull null
            val fraction = if (interval == 0L) 1.0 else overlap.toDouble() / interval
            record.metadata.dataOrigin.packageName to (value(record) * fraction)
        }.groupBy({ it.first }, { it.second }).mapValues { (_, values) -> values.sum() }
        return when (totals.size) {
            0 -> null
            1 -> Reading(format(totals.values.single()), totals.keys)
            else -> Reading(
                context.getString(R.string.source_count, totals.size),
                totals.keys,
                totals.entries.sortedBy { sourceLabel(it.key) }.map { (source, subtotal) ->
                    "${sourceLabel(source)} · ${format(subtotal)}"
                }
            )
        }
    }

    private fun <T : Any> aggregate(
        type: AggregationType<T>,
        range: TimeInstantRangeFilter,
        done: (Result<Reading?>) -> Unit,
        format: (T) -> String
    ) {
        val request = AggregateRecordsRequest.Builder<T>(range).addAggregationType(type).build()
        try {
            manager.aggregate(request, executor, object :
                OutcomeReceiver<AggregateRecordsResponse<T>, HealthConnectException> {
                override fun onResult(response: AggregateRecordsResponse<T>) {
                    val value = response.get(type)
                    val reading = value?.let {
                        Reading(format(it), response.getDataOrigins(type).map { origin -> origin.packageName }.toSet())
                    }
                    done(Result.success(reading))
                }

                override fun onError(error: HealthConnectException) = done(Result.failure(error))
            })
        } catch (error: RuntimeException) {
            done(Result.failure(error))
        }
    }

    private fun <T : Record> readRecords(
        type: Class<T>,
        range: TimeInstantRangeFilter,
        done: (Result<Reading?>) -> Unit,
        summarize: (List<T>) -> Reading?
    ) {
        val records = mutableListOf<T>()
        fun readPage(pageToken: Long?) {
            val builder = ReadRecordsRequestUsingFilters.Builder(type)
                .setTimeRangeFilter(range)
                .setPageSize(500)
            if (pageToken != null) builder.setPageToken(pageToken)
            try {
                manager.readRecords(builder.build(), executor, object :
                    OutcomeReceiver<ReadRecordsResponse<T>, HealthConnectException> {
                    override fun onResult(response: ReadRecordsResponse<T>) {
                        records.addAll(response.records)
                        if (response.nextPageToken == -1L) {
                            done(Result.success(summarize(records)))
                        } else {
                            readPage(response.nextPageToken)
                        }
                    }

                    override fun onError(error: HealthConnectException) = done(Result.failure(error))
                })
            } catch (error: RuntimeException) {
                done(Result.failure(error))
            }
        }
        readPage(null)
    }

    private fun summarizeHeart(
        records: List<HeartRateRecord>,
        start: Instant,
        end: Instant,
        zone: ZoneId
    ): Reading? {
        val byOrigin = records.flatMap { record ->
            record.samples.filter { it.time >= start && it.time < end }
                .map { record.metadata.dataOrigin.packageName to it }
        }.groupBy({ it.first }, { it.second })
        val latest = byOrigin.values.flatten().maxByOrNull { it.time } ?: return null
        val time = DateTimeFormatter.ofPattern("HH:mm").withZone(zone)
        val details = byOrigin.map { (origin, samples) ->
            val last = samples.maxBy { it.time }
            val value = context.getString(R.string.heart_value, last.beatsPerMinute.toString())
            val summary = context.getString(R.string.heart_summary, time.format(last.time), samples.size.toString())
            "${sourceLabel(origin)} · $value\n$summary"
        }
        return Reading(context.getString(R.string.heart_value, latest.beatsPerMinute.toString()), byOrigin.keys, details)
    }

    private fun summarizeSleep(
        records: List<SleepSessionRecord>,
        start: Instant,
        end: Instant,
        zone: ZoneId
    ): Reading? {
        val sessions = records.filter { it.endTime >= start && it.endTime < end }
            .sortedBy { it.startTime }
        if (sessions.isEmpty()) return null
        val time = DateTimeFormatter.ofPattern("M月d日 HH:mm").withZone(zone)
        val details = sessions.map {
            val duration = context.getString(R.string.sleep_time, time.format(it.startTime), time.format(it.endTime))
            "${sourceLabel(it.metadata.dataOrigin.packageName)}\n$duration"
        }
        val origins = sessions.map { it.metadata.dataOrigin.packageName }.toSet()
        return Reading(context.getString(R.string.sleep_value, sessions.size), origins, details)
    }
}
