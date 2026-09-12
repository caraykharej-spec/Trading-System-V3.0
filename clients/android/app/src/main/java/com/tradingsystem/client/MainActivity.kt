package com.tradingsystem.client

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject


class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { TradingSystemClient() }
    }
}


private enum class ClientScreen(val label: String) {
    DASHBOARD("Dashboard"),
    RANKING("Ranking"),
    POSITIONS("Positions"),
    PERFORMANCE("Performance"),
    ASSISTANT("Assistant"),
    SETTINGS("Settings"),
}


@Composable
private fun TradingSystemClient() {
    var selectedName by rememberSaveable { mutableStateOf(ClientScreen.DASHBOARD.name) }
    var baseUrl by rememberSaveable { mutableStateOf("") }
    var apiKey by remember { mutableStateOf("") }
    val selected = ClientScreen.valueOf(selectedName)
    val config = remember(baseUrl, apiKey) { ApiConfig(baseUrl = baseUrl, apiKey = apiKey) }
    val client = remember(config) { TradingApiClient(config) }

    MaterialTheme(colorScheme = darkColorScheme()) {
        Scaffold { padding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
            ) {
                Header()
                ScrollableTabRow(selectedTabIndex = selected.ordinal) {
                    ClientScreen.entries.forEach { screen ->
                        Tab(
                            selected = screen == selected,
                            onClick = { selectedName = screen.name },
                            text = { Text(screen.label) },
                        )
                    }
                }
                when (selected) {
                    ClientScreen.DASHBOARD -> DashboardScreen(client, config)
                    ClientScreen.RANKING -> EndpointScreen(
                        title = "Qualified Ranking",
                        path = "/opportunities?limit=10",
                        client = client,
                        config = config,
                    )
                    ClientScreen.POSITIONS -> EndpointScreen(
                        title = "Open Positions",
                        path = "/positions",
                        client = client,
                        config = config,
                    )
                    ClientScreen.PERFORMANCE -> EndpointScreen(
                        title = "Performance Analytics",
                        path = "/analytics/performance",
                        client = client,
                        config = config,
                    )
                    ClientScreen.ASSISTANT -> AssistantScreen(client, config)
                    ClientScreen.SETTINGS -> SettingsScreen(
                        baseUrl = baseUrl,
                        apiKey = apiKey,
                        onBaseUrlChanged = { baseUrl = it },
                        onApiKeyChanged = { apiKey = it },
                    )
                }
            }
        }
    }
}


@Composable
private fun Header() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 18.dp, vertical = 14.dp),
    ) {
        Text(
            "Trading System V3",
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
        )
        Text(
            "PAPER / SHADOW client · no live execution controls",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.primary,
        )
    }
}


@Composable
private fun DashboardScreen(client: TradingApiClient, config: ApiConfig) {
    var payloads by remember(client) { mutableStateOf<List<Pair<String, ApiPayload>>>(emptyList()) }
    var error by remember(client) { mutableStateOf<String?>(null) }
    var loading by remember(client) { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    fun refresh() {
        if (!config.isValidHttpsUrl()) {
            error = "Configure a valid HTTPS API URL in Settings."
            payloads = emptyList()
            return
        }
        scope.launch {
            loading = true
            error = null
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    listOf(
                        "Health" to client.get("/health"),
                        "Readiness" to client.get("/ready"),
                        "Universe Coverage" to client.get("/market-data/universe-coverage"),
                        "Top Opportunities" to client.get("/opportunities?limit=10"),
                    )
                }
            }
            payloads = result.getOrDefault(emptyList())
            error = result.exceptionOrNull()?.message
            loading = false
        }
    }

    LaunchedEffect(client) { refresh() }
    ScreenContainer {
        ScreenTitle("Dashboard", "Same API contract as the web dashboard")
        Button(onClick = { refresh() }, enabled = !loading) {
            Text(if (loading) "Refreshing…" else "Refresh")
        }
        error?.let { ErrorCard(it) }
        payloads.forEach { (name, payload) -> PayloadCard(name, payload) }
    }
}


@Composable
private fun EndpointScreen(
    title: String,
    path: String,
    client: TradingApiClient,
    config: ApiConfig,
) {
    var payload by remember(client, path) { mutableStateOf<ApiPayload?>(null) }
    var error by remember(client, path) { mutableStateOf<String?>(null) }
    var loading by remember(client, path) { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    fun refresh() {
        if (!config.isValidHttpsUrl()) {
            error = "Configure a valid HTTPS API URL in Settings."
            payload = null
            return
        }
        scope.launch {
            loading = true
            error = null
            val result = runCatching { withContext(Dispatchers.IO) { client.get(path) } }
            payload = result.getOrNull()
            error = result.exceptionOrNull()?.message
            loading = false
        }
    }

    LaunchedEffect(client, path) { refresh() }
    ScreenContainer {
        ScreenTitle(title, "Read-only backend evidence")
        Button(onClick = { refresh() }, enabled = !loading) {
            Text(if (loading) "Refreshing…" else "Refresh")
        }
        error?.let { ErrorCard(it) }
        payload?.let { PayloadCard(title, it) }
    }
}


@Composable
private fun AssistantScreen(client: TradingApiClient, config: ApiConfig) {
    var query by rememberSaveable { mutableStateOf("") }
    var payload by remember(client) { mutableStateOf<ApiPayload?>(null) }
    var error by remember(client) { mutableStateOf<String?>(null) }
    var loading by remember(client) { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    ScreenContainer {
        ScreenTitle(
            "Grounded Assistant",
            "Positions, journal, market change and bounded what-if analytics",
        )
        OutlinedTextField(
            value = query,
            onValueChange = { query = it.take(2000) },
            label = { Text("Query") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 2,
        )
        Button(
            onClick = {
                if (!config.isValidHttpsUrl()) {
                    error = "Configure a valid HTTPS API URL in Settings."
                } else if (query.isBlank()) {
                    error = "Enter a query first."
                } else {
                    scope.launch {
                        loading = true
                        error = null
                        val result = runCatching {
                            withContext(Dispatchers.IO) { client.postAssistant(query.trim()) }
                        }
                        payload = result.getOrNull()
                        error = result.exceptionOrNull()?.message
                        loading = false
                    }
                }
            },
            enabled = !loading,
        ) {
            Text(if (loading) "Loading…" else "Ask")
        }
        error?.let { ErrorCard(it) }
        payload?.let { PayloadCard("Assistant Response", it) }
    }
}


@Composable
private fun SettingsScreen(
    baseUrl: String,
    apiKey: String,
    onBaseUrlChanged: (String) -> Unit,
    onApiKeyChanged: (String) -> Unit,
) {
    ScreenContainer {
        ScreenTitle("Connection Settings", "Credentials are never hard-coded into the client")
        OutlinedTextField(
            value = baseUrl,
            onValueChange = onBaseUrlChanged,
            modifier = Modifier.fillMaxWidth(),
            label = { Text("HTTPS API base URL") },
            placeholder = { Text("https://api.example.com") },
            singleLine = true,
        )
        OutlinedTextField(
            value = apiKey,
            onValueChange = onApiKeyChanged,
            modifier = Modifier.fillMaxWidth(),
            label = { Text("X-API-Key") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
        )
        Text(
            "The API key is kept only in memory for this app session. " +
                "Cleartext HTTP is disabled by the Android manifest.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            "This client intentionally has no order submission, leverage, stop-loss, " +
                "take-profit, or live-trading controls.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.primary,
        )
    }
}


@Composable
private fun ScreenContainer(content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        content = content,
    )
}


@Composable
private fun ScreenTitle(title: String, subtitle: String) {
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        Text(
            subtitle,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}


@Composable
private fun PayloadCard(title: String, payload: ApiPayload) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(title, fontWeight = FontWeight.SemiBold)
                Text(
                    "HTTP ${payload.statusCode}",
                    color = if (payload.successful) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.error
                    },
                )
            }
            payload.requestId?.let {
                Text(
                    "Request: $it",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            SelectionContainer {
                Text(prettyJson(payload.body), style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}


@Composable
private fun ErrorCard(message: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
    ) {
        Text(
            message,
            modifier = Modifier.padding(14.dp),
            color = MaterialTheme.colorScheme.onErrorContainer,
        )
    }
}


private fun prettyJson(raw: String): String = runCatching {
    JSONObject(raw).toString(2)
}.getOrDefault(raw.ifBlank { "<empty response>" })
