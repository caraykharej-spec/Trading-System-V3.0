package com.tradingsystem.client

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test


class ApiConfigTest {
    @Test
    fun normalizesBaseUrlAndBuildsVersionedEndpoint() {
        val config = ApiConfig(" https://api.example.com/ ")
        assertEquals("https://api.example.com", config.normalizedBaseUrl())
        assertEquals(
            "https://api.example.com/api/v1/positions",
            config.endpoint("/positions"),
        )
    }

    @Test
    fun acceptsHttpsAndRejectsCleartextHttp() {
        assertTrue(ApiConfig("https://api.example.com").isValidHttpsUrl())
        assertFalse(ApiConfig("http://api.example.com").isValidHttpsUrl())
        assertFalse(ApiConfig("").isValidHttpsUrl())
    }
}
