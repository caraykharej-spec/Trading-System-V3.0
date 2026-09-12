package com.tradingsystem.client

import java.net.URI


data class ApiConfig(
    val baseUrl: String,
    val apiKey: String = "",
) {
    fun normalizedBaseUrl(): String = baseUrl.trim().trimEnd('/')

    fun endpoint(path: String): String =
        "${normalizedBaseUrl()}/api/v1/${path.trimStart('/')}"

    fun isValidHttpsUrl(): Boolean = runCatching {
        val uri = URI(normalizedBaseUrl())
        uri.scheme.equals("https", ignoreCase = true) && !uri.host.isNullOrBlank()
    }.getOrDefault(false)
}
