package com.mypark.totem

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Erro de API já com a mensagem pronta pra mostrar na tela (extraída do
 * campo "detail" da resposta, igual todo backend FastAPI deste projeto
 * devolve em erro).
 */
class ApiException(message: String) : Exception(message)

/**
 * Cliente HTTP mínimo pro backend (mesmo compartilhado por
 * gestão/operação/totens web, ver Config.BASE_URL) -- GET/POST simples
 * com Bearer token, sem biblioteca externa (nenhuma dependência de
 * rede além do que já vem no Android). Roda em background sempre --
 * nunca chame direto na UI thread.
 */
object Api {

    private const val TIMEOUT_MS = 15000

    fun get(path: String, token: String? = null): String =
        chamar("GET", path, token, null)

    fun post(path: String, token: String? = null, corpo: JSONObject? = null): String =
        chamar("POST", path, token, corpo ?: JSONObject())

    private fun chamar(metodo: String, path: String, token: String?, corpo: JSONObject?): String {
        val conn = URL(Config.BASE_URL + path).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = metodo
            conn.connectTimeout = TIMEOUT_MS
            conn.readTimeout = TIMEOUT_MS
            if (token != null) conn.setRequestProperty("Authorization", "Bearer $token")
            if (corpo != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(corpo.toString().toByteArray(Charsets.UTF_8)) }
            }
            val codigo = conn.responseCode
            val texto = (if (codigo in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""
            if (codigo == 401) throw ApiException("Sessão expirada -- faça login novamente")
            if (codigo !in 200..299) {
                val detalhe = try {
                    JSONObject(texto).optString("detail", "Erro $codigo")
                } catch (e: Exception) {
                    "Erro $codigo"
                }
                throw ApiException(detalhe)
            }
            return texto
        } catch (e: ApiException) {
            throw e
        } catch (e: Exception) {
            throw ApiException("Erro de conexão: ${e.message}")
        } finally {
            conn.disconnect()
        }
    }
}
