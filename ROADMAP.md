# Roadmap

Attività successive alla migrazione P0 a MCP Python SDK v2.

## P1 — Qualità, prestazioni e robustezza

### 1. Riutilizzare `UmamiClient` tramite lifespan MCP

- Introdurre un `AppContext` tipizzato contenente `UmamiClient`.
- Creare il client una sola volta all'avvio tramite `MCPServer(lifespan=...)`.
- Iniettarlo nei tool tramite `Context[AppContext]`.
- Chiuderlo correttamente allo shutdown.
- Rendere concorrente e sicuro il login username/password con un lock.
- In caso di `401`, invalidare il token e tentare una sola nuova autenticazione.

**Obiettivo:** riutilizzare il connection pool HTTP ed evitare un login Umami per ogni tool call.

**Criteri di completamento:**

- una sola istanza HTTP per il lifespan del server;
- test su startup e shutdown;
- test su chiamate concorrenti;
- test sul rinnovo del token dopo `401`.

### 2. Tipizzare gli output dei tool

Introdurre progressivamente modelli Pydantic per:

- `Website` e pagina dei website;
- statistiche;
- pageview e serie temporali;
- metriche;
- visitatori attivi.

Valutare inizialmente `extra="allow"` per tollerare differenze tra Umami Cloud e versioni self-hosted.

**Obiettivo:** produrre output schema MCP descrittivi e validare le risposte upstream.

**Criteri di completamento:**

- nessun tool pubblico restituisce `dict[str, Any]` o `list[dict[str, Any]]`;
- test degli output schema MCP;
- fixture rappresentative per Cloud e self-hosted;
- errori di validazione convertiti in messaggi controllati.

### 3. Rafforzare input e descrizioni dei tool

- Applicare limiti a `page`, `page_size`, `limit` e `offset`.
- Vincolare il tipo di metrica ai valori supportati da Umami.
- Validare la timezone tramite il database IANA.
- Validare o codificare in sicurezza `website_id` prima di inserirlo nel path.
- Documentare il range temporale predefinito di sette giorni.
- Aggiungere descrizioni Pydantic ai parametri.
- Correggere la descrizione di `get_websites`, che è paginato e non restituisce necessariamente tutti i siti.

**Criteri di completamento:** input invalidi rifiutati dallo schema prima della chiamata HTTP e schema facilmente interpretabile dal modello.

### 4. Sanitizzare errori e migliorare i retry

- Non propagare al modello il body arbitrario delle risposte Umami.
- Separare messaggi sicuri per il tool e dettagli diagnostici per log/telemetria.
- Distinguere autenticazione, rate limit, timeout, errore upstream e risposta non valida.
- Rispettare `Retry-After` sui `429`.
- Aggiungere exponential backoff con jitter.
- Ritentare solo gli errori di rete e i `5xx` idempotenti appropriati.
- Non attendere dopo l'ultimo tentativo.

**Criteri di completamento:** nessun secret o body upstream nei risultati MCP; retry deterministici e coperti da test.

### 5. Manutenzione e documentazione

- Allineare il requisito Python del README (`3.13+`) con `requires-python` e CI (`3.11+`), oppure cambiare esplicitamente la policy.
- Correggere il comando locale in `uvx umami-mcp-server`.
- Rendere validi gli esempi JSON del README.
- Verificare che gli artefatti `dist/` corrispondano alla versione pubblicata.
- Aggiungere uno smoke test del wheel in un ambiente pulito, senza riutilizzare `uv.lock`.

---

## P2 — Evoluzione MCP e osservabilità

### 1. Cache hints MCP

- Configurare `tools/list` con TTL di cinque minuti e scope `public`.
- Verificare che ordine e contenuto del catalogo restino deterministici.
- Conservare la compatibilità con la serializzazione legacy.

**Criteri di completamento:** `tools/list` restituisce `ttlMs == 300000` e
`cacheScope="public"` sul protocollo corrente, con test di determinismo e compatibilità.

### 2. OpenTelemetry

- Conservare il middleware OpenTelemetry fornito da MCP SDK.
- Aggiungere span applicativi e metriche per le richieste Umami.
- Propagare esclusivamente W3C Trace Context, senza baggage.
- Normalizzare endpoint e attributi per impedire leak e cardinalità incontrollata.
- Rendere SDK ed exporter facoltativi tramite l'extra `otel`.

**Criteri di completamento:** gerarchia MCP → Umami verificata, telemetria disattivabile,
metriche di latenza, errori, retry, rate limit e refresh disponibili, redaction coperta da test.

### 3. Guardrail MCP

- Mantenere stdio come unico trasporto applicativo.
- Conservare la superficie standard pubblicizzata da `MCPServer` 2.0.0.
- Non introdurre MCP Apps, Tasks, Roots, Sampling o Logging MCP.
- Continuare a usare il logging Python su stderr.

**Criteri di completamento:** il risultato pubblico di inizializzazione è coperto da test e
non pubblicizza logging, tasks o estensioni sperimentali.

### 4. Documentazione e release

- Documentare installazione, configurazione, redaction e troubleshooting OpenTelemetry.
- Pubblicare la versione `0.3.0`.
- Verificare separatamente il wheel base e il wheel con extra `otel`.
- Eliminare versioni package hardcoded dai workflow.

**Criteri di completamento:** documentazione operativa completa, metadata coerenti e smoke
test del wheel senza dipendenze da collector esterni.
