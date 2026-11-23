package io.awy.read

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.Inet6Address
import java.net.InetAddress
import java.net.SocketTimeoutException
import java.net.URL
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.Mac
import javax.crypto.SecretKey
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

/*
 * 和电脑配对、把数据传给电脑（只在同一个 Wi-Fi 里，决定 0014）。
 *
 * 找电脑：往局域网喊一声（UDP 广播 47824 端口），电脑上的 AlwaysWithYou 回一句自己的名字和编号。
 *        喊不到时（有的路由器不让设备互相发现）可以手动填电脑地址。
 * 配对：电脑上显示一个 12 位配对码（10 分钟有效、只能用一次、输错 5 次作废）。
 *      手机用配对码算出一把临时钥匙，证明自己知道配对码；电脑再用这把临时钥匙加密发来一把长期钥匙。
 *      配对码本身从不在网络上传。
 * 上传：每批数据用长期钥匙加密（AES-GCM），带递增的批次号，电脑只收比上次大的（防重放）；
 *      电脑回的「收到了」也是加密的，别人冒充不了。
 * 长期钥匙在手机上用系统「密钥库」里的另一把钥匙锁着，App 文件被拷走也解不开。
 */

class PairError(message: String) : Exception(message)

object Crypto {
    private val random = SecureRandom()

    fun bytes(n: Int) = ByteArray(n).also { random.nextBytes(it) }
    fun b64(data: ByteArray): String = Base64.encodeToString(data, Base64.NO_WRAP)
    fun unb64(text: String): ByteArray = Base64.decode(text, Base64.NO_WRAP)

    /** 配对码 → 临时钥匙。故意算得慢（20 万次），别人截到数据也没法一个个试配对码。 */
    fun pairKey(code: String, pcId: String): ByteArray {
        val spec = PBEKeySpec(code.toCharArray(), "awy-pair-v1:$pcId".toByteArray(), 200_000, 256)
        return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
    }

    fun hmac(key: ByteArray, message: String): ByteArray =
        Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(key, "HmacSHA256")) }.doFinal(message.toByteArray())

    fun seal(key: ByteArray, plain: ByteArray, aad: String): JSONObject {
        val iv = bytes(12)
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, iv))
        c.updateAAD(aad.toByteArray())
        return JSONObject().put("iv", b64(iv)).put("ct", b64(c.doFinal(plain)))
    }

    fun open(key: ByteArray, box: JSONObject, aad: String): ByteArray {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, unb64(box.getString("iv"))))
        c.updateAAD(aad.toByteArray())
        return c.doFinal(unb64(box.getString("ct")))
    }

    /** 配对码只认这 32 个字符；容易看错的 O/I/L 当作 0/1/1。 */
    fun normalizeCode(input: String): String = input.uppercase()
        .replace('O', '0').replace('I', '1').replace('L', '1')
        .filter { it in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" }
}

/** 用系统密钥库里的钥匙把长期钥匙锁起来（这把钥匙拿不出手机）。 */
object Vault {
    private const val ALIAS = "awy-wrap"

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return gen.generateKey()
    }

    fun wrap(data: ByteArray): String {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key())
        return Crypto.b64(c.iv + c.doFinal(data))
    }

    fun unwrap(text: String): ByteArray {
        val all = Crypto.unb64(text)
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, all.copyOfRange(0, 12)))
        return c.doFinal(all.copyOfRange(12, all.size))
    }
}

class PcLink(private val context: Context) {
    data class Pc(val host: String, val port: Int, val id: String, val name: String)
    private class HttpError(val code: Int, val body: String) : IOException("HTTP $code")

    private val prefs = Sync.prefs(context)
    private val inflight = File(context.filesDir, "inflight.json")

    val paired get() = prefs.contains("dev_key")
    val pcName get() = prefs.getString("pc_name", "") ?: ""
    val lastUpload get() = prefs.getLong("last_upload", 0)
    val lastError get() = prefs.getString("last_error", "") ?: ""

    /** 连着 Wi-Fi，或者手机自己开着热点（电脑连在手机热点上）时，才去找电脑、上传。 */
    fun onWifi(): Boolean {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val caps = cm.getNetworkCapabilities(cm.activeNetwork)
        if (caps != null && (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET))) return true
        return hotspotOn()
    }

    /** 手机开着热点：有一个热点网卡（ap0 / swlan0 / wlan1 之类）是开着的，并且有局域网地址。 */
    private fun hotspotOn(): Boolean = try {
        java.net.NetworkInterface.getNetworkInterfaces()?.toList().orEmpty().any { ni ->
            val n = ni.name.lowercase()
            ni.isUp && !ni.isLoopback && (n.startsWith("ap") || n.startsWith("swlan") || n.startsWith("softap") || n == "wlan1" || n == "wlan2") &&
                ni.inetAddresses.toList().any { it is java.net.Inet4Address && it.isSiteLocalAddress }
        }
    } catch (_: Exception) {
        false
    }

    // ---- 找电脑 ----------------------------------------------------------------

    private fun parsePc(host: String, text: String): Pc? = try {
        val j = JSONObject(text)
        if (j.optInt("awy") != 1) null
        else Pc(host, j.optInt("port", PORT), j.getString("pc"), j.optString("name", "电脑"))
    } catch (_: Exception) {
        null
    }

    /** 往局域网喊一声，收集回应（最多等 2 秒）。 */
    fun discover(): List<Pc> {
        val found = LinkedHashMap<String, Pc>()
        try {
            DatagramSocket().use { socket ->
                socket.broadcast = true
                socket.soTimeout = 700
                val ask = "AWY-DISCOVER 1".toByteArray()
                val target = InetAddress.getByName("255.255.255.255")
                repeat(3) {
                    socket.send(DatagramPacket(ask, ask.size, target, PORT))
                    val buf = ByteArray(1024)
                    while (true) {
                        val packet = DatagramPacket(buf, buf.size)
                        try {
                            socket.receive(packet)
                        } catch (_: SocketTimeoutException) {
                            break
                        }
                        val host = packet.address.hostAddress ?: continue
                        parsePc(host, String(packet.data, 0, packet.length))?.let { found.putIfAbsent(it.id, it) }
                    }
                    if (found.isNotEmpty()) return found.values.toList()
                }
            }
        } catch (_: IOException) {
        }
        return found.values.toList()
    }

    private fun url(host: String, port: Int, path: String): URL {
        val h = if (InetAddress.getByName(host) is Inet6Address) "[$host]" else host
        return URL("http://$h:$port$path")
    }

    /** 手动填了地址时：直接问那台电脑是谁。 */
    fun hello(host: String): Pc? = try {
        val c = url(host, PORT, "/phone/hello").openConnection() as HttpURLConnection
        c.connectTimeout = 3000
        c.readTimeout = 5000
        c.inputStream.bufferedReader().use { parsePc(host, it.readText()) }
    } catch (e: Exception) {
        android.util.Log.w("AwyRead", "连不上 $host", e)
        null
    }

    private fun post(host: String, port: Int, path: String, body: JSONObject): JSONObject {
        val c = url(host, port, path).openConnection() as HttpURLConnection
        c.connectTimeout = 4000
        c.readTimeout = 20000
        c.requestMethod = "POST"
        c.doOutput = true
        c.setRequestProperty("Content-Type", "application/json")
        c.outputStream.use { it.write(body.toString().toByteArray()) }
        val code = c.responseCode
        val text = (if (code in 200..299) c.inputStream else c.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
        if (code !in 200..299) throw HttpError(code, text)
        return JSONObject(text)
    }

    // ---- 配对 ----------------------------------------------------------------

    /** 成功返回电脑的名字；失败抛 PairError（里面是给人看的原因）。 */
    fun pair(codeInput: String, manualHost: String?): String {
        val code = Crypto.normalizeCode(codeInput)
        if (code.length != 12) throw PairError("配对码是 12 位，比如 7K3Q-9XMD-2PLF")
        val host = manualHost?.trim().orEmpty()
        val pc = (if (host.isNotEmpty()) hello(host) else discover().firstOrNull())
            ?: throw PairError(
                if (host.isNotEmpty()) "连不上 $host。确认电脑上开着 AlwaysWithYou 并打开了「手机」。" + ISOLATION
                else "没找到电脑。确认手机和电脑连的是同一个 Wi-Fi，电脑上打开了「手机」；也可以在下面手动填电脑地址。" + ISOLATION
            )
        val key = Crypto.pairKey(code, pc.id)
        val nonce = Crypto.b64(Crypto.bytes(16))
        val device = "${Build.MANUFACTURER} ${Build.MODEL}".trim()
        val body = JSONObject().put("v", 1).put("device", device).put("nonce", nonce)
            .put("proof", Crypto.b64(Crypto.hmac(key, "pair|$nonce|$device")))
        val reply = try {
            post(pc.host, pc.port, "/phone/pair", body)
        } catch (e: HttpError) {
            throw PairError(
                when (e.code) {
                    403 -> "配对码不对，或者已经过期了（10 分钟有效）。在电脑上重新点「配对新手机」"
                    429 -> "输错次数太多，这个配对码作废了。在电脑上重新点「配对新手机」"
                    else -> "电脑拒绝了配对（${e.code}）"
                }
            )
        } catch (e: IOException) {
            throw PairError("连接电脑失败：${e.message}")
        }
        val info = JSONObject(String(Crypto.open(key, reply, "pair-resp|$nonce")))
        prefs.edit()
            .putString("dev_id", info.getString("id"))
            .putString("dev_key", Vault.wrap(Crypto.unb64(info.getString("key"))))
            .putString("pc_id", pc.id)
            .putString("pc_name", info.optString("name", pc.name))
            .putString("pc_host", pc.host)
            .putInt("pc_port", pc.port)
            .putLong("seq", 0)
            .remove("last_error")
            .apply()
        inflight.delete()
        return pcName
    }

    fun unpair() {
        prefs.edit().remove("dev_id").remove("dev_key").remove("pc_id").remove("pc_name")
            .remove("pc_host").remove("pc_port").remove("seq").remove("last_upload").remove("last_error").apply()
        inflight.delete()
    }

    // ---- 上传 ----------------------------------------------------------------

    /** 已配对、连着 Wi-Fi 时，把队列里的数据传给电脑。返回给界面看的一句话。 */
    fun upload(queue: Queue): String {
        if (!paired) return "还没和电脑配对"
        if (!onWifi()) return "没连 Wi-Fi，回家连上后再传"
        // （连着 Wi-Fi 但连不上电脑时，见下面「找不到电脑」的提示）
        val devId = prefs.getString("dev_id", "")!!
        val key = try {
            Vault.unwrap(prefs.getString("dev_key", "")!!)
        } catch (e: Exception) {
            return fail("手机上的钥匙打不开了，请重新配对")
        }
        var host = prefs.getString("pc_host", "")!!
        var port = prefs.getInt("pc_port", PORT)
        var sent = 0
        var rediscovered = false
        for (round in 0 until 50) {
            val batch = nextBatch(queue) ?: break
            val seq = batch.getLong("seq")
            val box = Crypto.seal(key, batch.toString().toByteArray(), "up|$devId")
            val body = JSONObject().put("v", 1).put("id", devId).put("iv", box.getString("iv")).put("ct", box.getString("ct"))
            val reply = try {
                post(host, port, "/phone/upload", body)
            } catch (e: HttpError) {
                return when (e.code) {
                    403 -> fail("电脑上已经取消了这台手机的配对，请重新配对")
                    409 -> {   // 批次号比电脑记的小（比如手机数据被清过）：跟上电脑的号，下次再传
                        val last = try { JSONObject(e.body).optLong("last", seq) } catch (_: Exception) { seq }
                        batch.put("seq", last + 1)
                        inflight.writeText(batch.toString())
                        prefs.edit().putLong("seq", last + 1).apply()
                        fail("批次号对不上，已经调整，下次会接着传")
                    }
                    else -> fail("电脑没收下（${e.code}）")
                }
            } catch (e: IOException) {
                if (rediscovered) return fail("连不上电脑（${e.message}）")
                rediscovered = true
                val pc = discover().firstOrNull { it.id == prefs.getString("pc_id", "") }
                    ?: return fail("找不到电脑：电脑可能关着、没开 AlwaysWithYou，或者现在连的不是和电脑同一个 Wi-Fi")
                host = pc.host
                port = pc.port
                prefs.edit().putString("pc_host", host).putInt("pc_port", port).apply()
                continue
            }
            val ack = try {
                JSONObject(String(Crypto.open(key, reply, "ack|$devId")))
            } catch (e: Exception) {
                return fail("电脑的回应对不上钥匙，没删手机上的数据")
            }
            if (ack.optLong("ack", -1) != seq) return fail("电脑的回应不对，没删手机上的数据")
            sent += batch.getJSONArray("events").length()
            inflight.delete()
            prefs.edit().putLong("last_upload", System.currentTimeMillis()).remove("last_error").apply()
        }
        return if (sent > 0) "已传给 $pcName：$sent 条" else "没有新数据要传"
    }

    private fun fail(message: String): String {
        prefs.edit().putString("last_error", message).apply()
        return message
    }

    /** 上次没传成功的那批先传；没有的话从队列里取一批（最多 400 条），编上新的批次号。 */
    private fun nextBatch(queue: Queue): JSONObject? {
        if (inflight.exists()) {
            try {
                return JSONObject(inflight.readText())
            } catch (_: Exception) {
                inflight.delete()
            }
        }
        val lines = queue.peek(400)
        if (lines.isEmpty()) return null
        val seq = prefs.getLong("seq", 0) + 1
        val events = JSONArray()
        lines.forEach { line -> try { events.put(JSONObject(line)) } catch (_: Exception) {} }
        val batch = JSONObject().put("seq", seq).put("sent", Sync.iso(System.currentTimeMillis())).put("events", events)
        inflight.writeText(batch.toString())   // 先存好这一批，再从队列里拿掉：中途断电也不会丢
        prefs.edit().putLong("seq", seq).commit()
        queue.drop(lines.size)
        return batch
    }

    companion object {
        const val PORT = 47824
        /** 公司 / 学校的 Wi-Fi 常常开着「设备隔离」：连在上面的手机和电脑互相看不见。 */
        const val ISOLATION = "\n\n如果是公司、学校这类 Wi-Fi，它可能不让设备互相连接，这时没法配对：回家用家里的 Wi-Fi 配对，或者让手机连电脑开的「移动热点」。"
    }
}
