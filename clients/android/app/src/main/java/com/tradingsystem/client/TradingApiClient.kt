package com.tradingsystem.client

import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL


data class ApiPayload(
    val statusCode: Int,
    val body: String,
    val requestId: String?,
) {
    val successful: Boolean get() = statusCode in 200..299
}


class TradingApiClient(private val config: ApiConfig) {
    fun get(path: String): ApiPayload = request("GET", path, null)

    fun postAssistant(query: String): ApiPayload {
        val body = JSONObject().put("query", query).toString()
        return request("POST", "/assistant/query", body)
    }

    private fun request(method: String, path: String, body: String?): ApiPayload {
        require(config.isValidHttpsUrl()) { "API base URL must be a valid HTTPS URL" }
        val connection = URL(config.endpoint(path)).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 15_000
            connection.readTimeout = 20_000
            connection.setRequestProperty("Accept", "application/json")
            if (config.apiKey.isNotBlank()) {
                connection.setRequestProperty("X-API-Key", config.apiKey)
            }
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.bufferedWriter(Charsets.UTF_8).use { it.write(body) }
            }

            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val responseBody = if (stream == null) {
                ""
            } else {
                BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { reader ->
                    reader.readText()
                }
            }
            return ApiPayload(
                statusCode = status,
                body = responseBody,
                requestId = connection.getHeaderField("X-Request-ID"),
            )
        } finally {
            connection.disconnect()
        }
    }
}
