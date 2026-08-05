# Piano di implementazione P2

## Scopo

Questo documento traduce il perimetro approvato della fase **P2 — Evoluzione MCP e
osservabilità** di [`ROADMAP.md`](ROADMAP.md) in un piano implementativo eseguibile.

La P2 deve portare il progetto alla release **`0.3.0`** introducendo:

- cache hint MCP per il catalogo statico dei tool;
- tracing e metriche OpenTelemetry per le chiamate verso Umami;
- propagazione sicura del trace context ricevuto tramite MCP;
- test espliciti di determinismo e redaction;
- documentazione operativa dell'osservabilità;
- regressioni che impediscano di pubblicizzare funzionalità MCP non adottate.

Il server continua a usare **stdio come unico trasporto applicativo** in questa fase.

---

## Decisioni definitive

### Cache del catalogo

- Metodo cacheable: `tools/list`.
- TTL: **300.000 ms** (cinque minuti).
- Scope: **`public`**.
- La scope pubblica è valida perché nomi, descrizioni e JSON Schema dei tool sono statici e
  non contengono dati Umami, identificatori di website o credenziali.
- Ordine e contenuto del catalogo devono essere deterministici.
- I cache hint sono garantiti sulla revisione MCP corrente `2026-07-28`; la serializzazione
  legacy deve restare compatibile con la propria superficie di protocollo.

### OpenTelemetry MCP

- Conservare il middleware OpenTelemetry fornito automaticamente da MCP SDK.
- Non aggiungere un secondo middleware per i tool, evitando span server duplicati.
- Usare gli span MCP esistenti come parent delle operazioni verso Umami.
- Non configurare un exporter globale nel codice della libreria.
- Il package base dichiara soltanto OpenTelemetry API e resta no-op senza SDK/exporter.
- Fornire l'extra facoltativo `umami-mcp-server[otel]` con OpenTelemetry SDK, distro ed
  exporter OTLP.
- La disattivazione esplicita usa la variabile standard:

  ```text
  OTEL_SDK_DISABLED=true
  ```

### OpenTelemetry Umami

- Una chiamata analytics produce un solo span logico, anche quando effettua più invii HTTP.
- Il login produce uno span separato e figlio dell'operazione che lo richiede.
- Il trace context inviato a Umami contiene esclusivamente W3C `traceparent` e `tracestate`.
- Non propagare baggage ricevuto dal client MCP.
- Non usare l'instrumentazione HTTPX automatica: il client emette telemetria applicativa con
  endpoint normalizzati e attributi controllati.
- Non registrare eccezioni grezze negli span.

### Redaction e cardinalità

Sono ammessi soltanto attributi appartenenti a una allowlist applicativa:

```text
http.request.method
http.response.status_code
umami.endpoint
umami.auth.mode
umami.retry.count
umami.outcome
umami.retry.cause
error.type
```

Non registrare mai:

- API key, bearer token, username o password;
- header e body HTTP;
- URL completi o query string;
- `website_id` o altri UUID concreti;
- search, filtri, date e timezone inviate dal tool;
- payload MCP o Umami;
- messaggi grezzi di eccezioni HTTPX o Pydantic.

Gli endpoint devono essere normalizzati, per esempio:

```text
/websites
/websites/{websiteId}/stats
/websites/{websiteId}/pageviews
/websites/{websiteId}/metrics
/websites/{websiteId}/metrics/expanded
/websites/{websiteId}/active
/auth/login
```

### Metriche

Introdurre i seguenti strumenti:

```text
umami.client.request.duration
umami.client.request.errors
umami.client.retries
umami.client.rate_limits
umami.client.token.refreshes
```

Semantica:

- `request.duration`: istogramma della durata della richiesta analytics logica, inclusi login
  o retry necessari a completarla;
- `request.errors`: un incremento per richiesta logica conclusa con errore;
- `retries`: un incremento per ogni nuovo invio, con causa normalizzata;
- `rate_limits`: un incremento per ogni risposta `429`, anche se un tentativo successivo ha
  successo;
- `token.refreshes`: un incremento soltanto quando un `401` provoca realmente un nuovo
  login, non quando una coroutine riutilizza il token già aggiornato da un'altra.

Le label devono restare a cardinalità limitata: endpoint logico, metodo, categoria dell'esito
ed eventuale causa normalizzata del retry.

### Funzionalità MCP non adottate

- MCP Apps non viene introdotto senza un requisito di visualizzazione interattiva.
- Tasks non viene introdotto: MCP SDK `2.0.0` non offre una superficie server conforme alla
  revisione corrente.
- Roots e Sampling non vengono utilizzati: sono capability client e il server non invia le
  relative richieste.
- Logging MCP non viene registrato.
- La superficie standard di `MCPServer` 2.0.0 resta invariata, incluse le capability
  `prompts` e `resources` predisposte automaticamente dall'SDK.
- Il logging diagnostico applicativo continua a usare il modulo Python `logging` su stderr.

---

## Stato iniziale

### Server MCP

[`src/umami_mcp_server/server.py`](src/umami_mcp_server/server.py):

- usa MCP SDK `2.0.0` e protocollo corrente `2026-07-28`;
- registra cinque tool in ordine deterministico;
- non configura ancora `cache_hints`;
- beneficia già dell'`OpenTelemetryMiddleware` installato dal low-level server MCP;
- condivide un solo `UmamiClient` per lifespan.

### Client Umami

[`src/umami_mcp_server/umami_client.py`](src/umami_mcp_server/umami_client.py):

- normalizza già gli UUID nei log tramite `_logical_endpoint()`;
- distingue autenticazione, rate limit, timeout, rete, upstream e risposta invalida;
- conosce numero dei tentativi, status e causa dei retry;
- non emette ancora span o metriche;
- non propaga ancora il trace context verso Umami.

### Dipendenze

- `opentelemetry-api==1.44.0` è installato transitivamente da MCP SDK, ma non è dichiarato
  come dipendenza diretta del progetto.
- `opentelemetry-sdk` non è installato nel gruppo di sviluppo.
- Nessun exporter è configurato.

### Test

La baseline verificata è:

```text
73 passed, 1 skipped
```

[`tests/test_server.py`](tests/test_server.py) verifica già ordine, schema, lifespan e
compatibilità legacy, ma non i cache hint o l'identità completa di due cataloghi consecutivi.

[`tests/test_umami_client.py`](tests/test_umami_client.py) copre già retry, rate limit,
refresh e sanitizzazione, fornendo i casi su cui verificare gli effetti OpenTelemetry.

---

# Fasi di implementazione

## Fase 1 — Allineamento del perimetro

### `ROADMAP.md`

Aggiornare P2 affinché descriva soltanto le capacità previste per questa release:

- cache hint;
- OpenTelemetry;
- guardrail sulle funzionalità MCP non adottate;
- documentazione e release.

Le attività non previste nella `0.3.0` non devono comparire tra i criteri di completamento
correnti.

### Criterio di completamento

Il contenuto della roadmap, questo piano e i test di accettazione descrivono lo stesso
perimetro.

---

## Fase 2 — Cache hint del catalogo

### `src/umami_mcp_server/server.py`

Importare:

```python
from mcp.server.caching import CacheHint
```

Aggiungere al costruttore di `MCPServer`:

```python
cache_hints={
    "tools/list": CacheHint(
        ttl_ms=300_000,
        scope="public",
    ),
},
```

Non modificare i singoli tool e non costruire manualmente `ListToolsResult`: il serializer
SDK applica già il hint nel punto corretto.

### `tests/test_server.py`

Aggiungere un test dedicato che, con `cache_mode="bypass"`, verifichi:

```python
assert result.ttl_ms == 300_000
assert result.cache_scope == "public"
```

Rafforzare il test di determinismo:

1. eseguire due `list_tools(cache_mode="bypass")` nella stessa sessione;
2. confrontare i tool completi serializzati con alias MCP;
3. mantenere il controllo esplicito dell'ordine:
   - `get_websites`;
   - `get_stats`;
   - `get_pageviews`;
   - `get_metrics`;
   - `get_active`.

Il test legacy esistente deve continuare a verificare il catalogo senza richiedere campi che
la relativa versione del protocollo non serializza.

### Criteri di completamento

- `tools/list` corrente restituisce TTL positivo e scope pubblica;
- due cataloghi consecutivi sono identici;
- la compatibilità legacy resta verde.

---

## Fase 3 — Modulo di telemetria

### Nuovo file: `src/umami_mcp_server/telemetry.py`

Centralizzare in questo modulo:

- instrumentation scope del progetto;
- tracer e meter ottenuti dalle API globali OpenTelemetry;
- creazione degli strumenti metrici;
- nomi di span, metriche e attributi;
- normalizzazione dell'endpoint;
- propagazione W3C in un carrier HTTP dedicato;
- mapping da eccezione applicativa a categoria sicura;
- helper per registrare durata, retry, rate limit, refresh ed errore finale.

Lo scope di instrumentation deve avere un nome stabile, per esempio:

```text
umami-mcp-server
```

Il modulo non deve:

- importare OpenTelemetry SDK;
- installare provider globali;
- scegliere exporter;
- leggere credenziali;
- ricevere o serializzare payload applicativi.

### Naming degli span

Usare nomi formati esclusivamente da metodo ed endpoint logico:

```text
umami.request GET /websites/{websiteId}/stats
umami.auth.login
```

Non includere UUID, hostname o parametri.

### Gestione errori

Gli span devono usare:

```text
record_exception=False
set_status_on_exception=False
```

In caso di fallimento impostare soltanto:

- status `ERROR` con descrizione controllata;
- `error.type` uguale alla categoria applicativa, non al testo dell'eccezione.

### Criteri di completamento

- il modulo dipende soltanto da `opentelemetry-api`;
- tutti gli strumenti e gli attributi sono definiti in un solo punto;
- nessun helper accetta body, header completi o URL arbitrari.

---

## Fase 4 — Strumentazione di `UmamiClient`

### `src/umami_mcp_server/umami_client.py`

#### `_request()`

Aprire lo span logico prima di `_ensure_token()`, così login e refresh risultano suoi figli e
la durata include l'intera operazione percepita dal tool.

Durante il loop:

- incrementare `umami.client.retries` prima di ogni `continue` che provoca un nuovo invio;
- usare cause chiuse e stabili:
  - `authentication_refresh`;
  - `timeout`;
  - `network`;
  - `rate_limit`;
  - `server_error`;
- incrementare `umami.client.rate_limits` a ogni `429`;
- aggiornare `umami.retry.count` con il numero totale di nuovi invii;
- impostare `http.response.status_code` soltanto con il codice osservato, senza body;
- registrare durata e risultato in `finally`.

Una richiesta che fallisce dopo tutti i tentativi incrementa `request.errors` una sola volta.
Una richiesta che incontra un errore transitorio e poi riesce non incrementa `request.errors`.

#### `_login()`

Creare lo span `umami.auth.login` senza attributi contenenti username, API base o body JSON.
Registrare soltanto status finale, modalità di autenticazione e categoria sicura dell'errore.

#### `_refresh_token()`

Incrementare `umami.client.token.refreshes` solo nel ramo che esegue `_login()`. Le coroutine
che trovano un token già sostituito non incrementano il contatore.

#### Propagazione HTTP

Prima dell'invio costruire un dizionario header contenente:

- l'eventuale `Authorization` già gestita dal client;
- i campi iniettati da `TraceContextTextMapPropagator`.

Non usare il propagatore globale, così il baggage non viene inoltrato.

### Concorrenza

La strumentazione non deve cambiare la semantica dei lock esistenti:

- un solo login iniziale concorrente;
- un solo refresh effettivo per token scaduto;
- metriche coerenti anche quando più richieste attendono lo stesso lock.

### Criteri di completamento

- ogni tool call crea al massimo uno span analytics logico;
- retry e refresh sono contati secondo la semantica definita;
- il comportamento HTTP e gli errori pubblici restano invariati;
- nessuna telemetria altera budget o delay dei retry.

---

## Fase 5 — Test OpenTelemetry

### Dipendenze di test

Aggiungere `opentelemetry-sdk` al gruppo dev per usare exporter e reader in-memory.

Usare provider condivisi dalla sessione di test e pulire gli exporter tra i test, evitando di
sostituire ripetutamente provider globali OpenTelemetry nello stesso processo.

### Nuovo file: `tests/test_telemetry.py`

#### Tracing MCP → Umami

Verificare che:

- il server MCP accetti un `traceparent` in `_meta`;
- lo span Umami discenda dallo span `tools/call` creato dall'SDK;
- l'header `traceparent` raggiunga `httpx.MockTransport`;
- l'eventuale baggage MCP non raggiunga Umami.

#### Retry e status

Coprire almeno:

- successo al primo tentativo: `umami.retry.count == 0`;
- successo al terzo invio: `umami.retry.count == 2`;
- errore finale: status span `ERROR` e una sola metrica `request.errors`;
- `429` seguito da successo: rate limit e retry incrementati, nessun errore logico finale;
- refresh dopo `401`: un solo refresh effettivo.

#### Metriche

Con un metric reader in-memory verificare:

- presenza e unità degli strumenti;
- durata registrata sia su successo sia su errore;
- valori dei counter;
- label limitate all'allowlist.

#### Redaction

Usare valori sintetici riconoscibili per:

- API key;
- username e password;
- bearer token;
- UUID;
- search e filtro;
- body di errore upstream.

Serializzare span, eventi, status description e data point metrici esportati, quindi verificare
che nessuno di questi valori sia presente.

#### Telemetria disabilitata

Testare `OTEL_SDK_DISABLED=true` in un subprocess, perché provider e strumenti OpenTelemetry
sono globali e devono essere inizializzati dopo la variabile environment.

### `tests/test_umami_client.py`

Mantenere qui i test funzionali esistenti di retry e autenticazione. Aggiungere soltanto le
asserzioni strettamente necessarie a verificare che gli header di propagazione non
sovrascrivano gli header auth.

### Criteri di completamento

- gerarchia MCP → Umami verificata;
- metriche richieste coperte;
- redaction verificata su tutti i canali esportabili;
- suite deterministica, senza dipendenze da collector esterni.

---

## Fase 6 — Capability guardrail

### `tests/test_server.py`

Estendere il test di negoziazione o aggiungerne uno dedicato per verificare che il server:

- conservi la superficie standard pubblicizzata da `MCPServer` 2.0.0;
- non pubblicizzi estensioni MCP non registrate, Logging MCP o Tasks;
- non utilizzi le capability client Roots o Sampling.

Il test deve controllare il risultato di inizializzazione pubblico, non attributi privati del
server SDK. Roots e Sampling, essendo capability client, non sono campi del risultato di
inizializzazione del server.

### Criterio di completamento

Un aggiornamento futuro dell'SDK non può abilitare accidentalmente funzionalità escluse senza
far fallire un test visibile.

---

## Fase 7 — Dipendenze e packaging

### `pyproject.toml`

- Aggiornare la versione a `0.3.0`.
- Dichiarare direttamente `opentelemetry-api`.
- Aggiungere l'extra facoltativo `otel` contenente OpenTelemetry SDK, distro ed exporter
  OTLP.
- Aggiungere `opentelemetry-sdk` al gruppo dev.
- Non aggiungere SDK o exporter alle dipendenze runtime obbligatorie del package base.

### `uv.lock`

Rigenerare il lockfile dopo le modifiche alle dipendenze.

### `.github/workflows/ci.yml`

Il wheel smoke deve verificare che:

- il package base si installi senza extra di osservabilità;
- il modulo server sia importabile;
- stdio parta senza richiedere OpenTelemetry SDK;
- la versione installata corrisponda a quella letta da `pyproject.toml`.

Aggiungere un secondo smoke test che installi il wheel con extra `otel` e verifichi la
presenza di SDK, distro ed exporter OTLP senza contattare un collector esterno.

Rimuovere l'asserzione hardcoded su `0.2.0`.

### `.github/workflows/publish.yml`

- Conservare il controllo tag → `project.version`.
- Nel virtualenv del wheel confrontare la versione installata con la versione del progetto,
  senza duplicare `0.3.0` nello script.
- Verificare che `opentelemetry-api` compaia nei metadata runtime.

### Criteri di completamento

- wheel base funzionante senza exporter;
- metadata coerenti;
- nessuna versione duplicata nei workflow;
- tag, progetto e wheel concordano.

---

## Fase 8 — Documentazione

### `README.md`

Aggiungere una sezione sintetica che documenti:

- cache pubblica di `tools/list` per cinque minuti;
- tracing MCP già fornito dall'SDK;
- span e metriche Umami aggiunti dal progetto;
- telemetria no-op senza SDK/exporter;
- `OTEL_SDK_DISABLED=true`;
- link alla guida completa di osservabilità.

### Nuovo file: `docs/observability.md`

Documentare:

- installazione tramite extra `umami-mcp-server[otel]`;
- modello di tracing MCP → Umami;
- nomi di span, metriche, attributi e unità;
- policy di redaction;
- variabili standard OpenTelemetry;
- configurazione di `OTEL_SERVICE_NAME`;
- esempio OTLP;
- disattivazione;
- troubleshooting senza stampare configurazioni sensibili.

La guida deve chiarire che le credenziali dell'exporter, come eventuali header OTLP, sono
secret operativi e non devono essere incluse in issue, log o configurazioni MCP condivise.

### Criteri di completamento

- un operatore può attivare o disattivare la telemetria senza modificare il codice;
- la documentazione distingue chiaramente API, SDK ed exporter OpenTelemetry;
- la policy di redaction coincide con i test.

---

# Ordine consigliato dei commit

1. Allineamento di roadmap e criteri P2.
2. Cache hint `tools/list` e test di determinismo.
3. Dipendenza API e nuovo modulo `telemetry.py`.
4. Span e propagazione nel client Umami.
5. Metriche di durata, errori, retry, rate limit e refresh.
6. Test OpenTelemetry e redaction.
7. Capability guardrail.
8. README e guida di osservabilità.
9. Versione `0.3.0`, lockfile e workflow senza versione hardcoded.

Ogni commit deve lasciare il prodotto funzionante end-to-end e la suite verde.

---

# Criteri finali di accettazione

## Cache

- `tools/list` restituisce `ttlMs == 300000` e `cacheScope == "public"` sul protocollo
  corrente.
- Ordine e contenuto del catalogo sono deterministici.
- La compatibilità legacy resta funzionante.

## Tracing

- Gli span MCP esistenti sono conservati senza duplicati.
- Ogni richiesta Umami produce uno span client con endpoint normalizzato.
- Il trace context MCP è propagato tramite W3C Trace Context.
- Il baggage non è inoltrato.
- Il tracing è no-op senza exporter ed esplicitamente disattivabile.

## Metriche

- Sono esportabili latenza, errori, retry, rate limit e refresh token.
- Counter e attributi rispettano la semantica definita.
- Le label hanno cardinalità limitata.

## Sicurezza

- Nessun secret, payload, UUID concreto o query compare in span, eventi, status o metriche.
- Nessuna eccezione grezza viene registrata negli span.
- La redaction è coperta da test automatici.

## Protocollo

- Il server conserva la superficie standard di `MCPServer` senza pubblicizzare Logging,
  Tasks o estensioni sperimentali.
- Roots e Sampling non vengono utilizzati.
- Non vengono introdotte API MCP deprecate.

## Release

- Versione progetto e wheel: `0.3.0`.
- Ruff, Pyright e Pytest passano su Python 3.11–3.14.
- Il wheel base funziona senza OpenTelemetry SDK o exporter.
- Il wheel con extra `otel` installa correttamente SDK, distro ed exporter OTLP.
- CI e publish non contengono una versione package hardcoded.

---

# File coinvolti

## Esistenti

- `ROADMAP.md` — perimetro e criteri P2.
- `src/umami_mcp_server/server.py` — cache hint e superficie MCP.
- `src/umami_mcp_server/umami_client.py` — span, propagazione e metriche.
- `tests/test_server.py` — cache, determinismo e capability.
- `tests/test_umami_client.py` — regressioni HTTP/auth.
- `tests/conftest.py` — isolamento delle variabili OpenTelemetry usate dai test.
- `pyproject.toml` — versione e dipendenze.
- `uv.lock` — lockfile aggiornato.
- `README.md` — documentazione sintetica.
- `.github/workflows/ci.yml` — suite e wheel smoke.
- `.github/workflows/publish.yml` — coerenza della release.

## Nuovi

- `src/umami_mcp_server/telemetry.py` — strumenti, naming e redaction OpenTelemetry.
- `tests/test_telemetry.py` — tracing, metriche e redaction.
- `docs/observability.md` — configurazione operativa.
