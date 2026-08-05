# Piano di implementazione P1

## Scopo

Questo documento traduce la sezione **P1 — Qualità, prestazioni e robustezza** di
[`ROADMAP.md`](ROADMAP.md) in un piano implementativo eseguibile.

La P1 deve portare il progetto alla release **`0.2.0`**, migliorando il ciclo di vita del
client HTTP, i contratti MCP, la validazione, gli errori, i retry, i test e il packaging.

## Decisioni definitive

### Compatibilità Umami

- Supporto ufficiale:
  - **Umami Cloud corrente**, tramite `https://api.umami.is/v1`;
  - **Umami self-hosted v3.x**, tramite la root `/api` dell'istanza.
- Umami v1 è esclusa.
- Umami v2 non fa parte della P1. Un suo eventuale supporto futuro dovrà essere
  un'integrazione separata, con contratto e mapping espliciti, senza introdurre fallback o
  branching v2 nel client v3.
- Il suffisso `/v1` della API Cloud non indica la versione dell'applicazione self-hosted.
- Le differenze additive fra Cloud, self-hosted e minor release v3 saranno tollerate tramite
  modelli Pydantic con `extra="allow"` e campi opzionali dove il contratto non è stabile.

### Contratto applicativo

- `website_id` sarà un UUID validato prima della chiamata HTTP.
- Limiti degli input:
  - `page >= 1`;
  - `1 <= page_size <= 100`;
  - `1 <= limit <= 500`;
  - `0 <= offset <= 10000`.
- Saranno supportati tutti i filtri documentati per Umami v3.
- Le unità temporali includeranno `minute`, oltre a `hour`, `day`, `month` e `year`.
- Il range predefinito resta di **sette giorni**.
- Python supportato: **3.11+**.
- Tutti i modelli di output iniziali useranno `extra="allow"`.

### Retry e autenticazione

- Ogni richiesta analytics avrà al massimo **3 invii HTTP totali**: richiesta iniziale più
  al massimo due nuovi tentativi.
- Le richieste di login sono separate dal budget degli invii analytics.
- Una singola richiesta logica può provocare al massimo un refresh del token dopo `401`.
- Il resend successivo al refresh rientra nei 3 invii analytics totali.
- `Retry-After` ha precedenza sul backoff calcolato, con attesa massima di 60 secondi.
- La release risultante sarà **`0.2.0`**.

---

## Stato iniziale

### Server MCP

[`src/umami_mcp_server/server.py`](src/umami_mcp_server/server.py) crea attualmente un
nuovo `UmamiClient` per ogni tool tramite `_umami_client()`. Di conseguenza:

- il connection pool di `httpx.AsyncClient` non viene riutilizzato;
- username/password causano un nuovo login a ogni tool call;
- non esiste un contesto applicativo condiviso dal lifespan MCP.

### Client Umami

[`src/umami_mcp_server/umami_client.py`](src/umami_mcp_server/umami_client.py):

- non sincronizza i login concorrenti;
- non rinnova il token dopo `401`;
- include body upstream ed eccezioni HTTP grezze in alcuni errori;
- non distingue autenticazione, timeout, rate limit, errore upstream e risposta non valida;
- non rispetta `Retry-After`;
- non ritenta i `5xx` transitori;
- attende anche dopo l'ultimo tentativo;
- restituisce `Any` da tutti i metodi pubblici.

### Modelli e schema MCP

[`src/umami_mcp_server/models.py`](src/umami_mcp_server/models.py) contiene soltanto gli
helper temporali e `Filters`. I tool pubblici restituiscono ancora `dict[str, Any]` o
`list[dict[str, Any]]`, producendo output schema MCP generici.

### Packaging

- `README.md` dichiara Python 3.13+, mentre package e CI supportano 3.11+.
- Il sorgente è ancora `0.1.1`, ma la `0.1.1` pubblicata precede la migrazione a MCP SDK v2.
- Gli artefatti locali ignorati in `dist/` sono `0.1.0` e sono obsoleti.
- Non esiste uno smoke test del wheel installato senza `uv.lock`.

---

# Fasi di implementazione

## Fase 1 — Fixture e contratto Umami v3

Prima di rendere obbligatori i campi Pydantic, congelare il contratto con fixture statiche.

### Struttura prevista

```text
tests/fixtures/
├── README.md
├── cloud_current/
│   ├── websites.json
│   ├── stats.json
│   ├── pageviews.json
│   ├── pageviews_compare.json
│   ├── metrics.json
│   ├── metrics_expanded.json
│   └── active.json
└── self_hosted_v3/
    ├── websites.json
    ├── stats.json
    ├── pageviews.json
    ├── pageviews_compare.json
    ├── metrics.json
    ├── metrics_expanded.json
    └── active.json
```

### Fixture self-hosted v3

Usare un ambiente usa-e-getta con una versione Umami v3 esatta, non `latest`:

1. avviare Umami v3 e PostgreSQL con Docker Compose;
2. accedere con l'account iniziale e cambiare la password di default;
3. creare un website di test;
4. generare pageview ed eventi sintetici tramite tracker o `/api/send`;
5. autenticarsi tramite `/api/auth/login`;
6. acquisire le risposte dei sette casi sopra;
7. sanitizzare UUID, domini, username e timestamp identificativi, preservando tipi e shape;
8. distruggere ambiente e volume con `docker compose down -v`.

Le fixture non devono contenere token, password, header, email, domini reali o dati utente.
`tests/fixtures/README.md` deve registrare:

- versione Umami esatta;
- backend database;
- endpoint e parametri usati;
- data di acquisizione;
- trasformazioni effettuate durante la sanitizzazione.

La generazione delle fixture è manuale e non fa parte della CI ordinaria.

### Fixture Cloud

Poiché l'accesso API non è disponibile nel piano Cloud gratuito:

- derivare le fixture dal contratto e dagli esempi ufficiali correnti;
- integrare le informazioni con l'implementazione upstream Umami v3;
- indicare URL e data di consultazione in `tests/fixtures/README.md`;
- non descriverle come risposte catturate da un account reale.

Un test Cloud live resterà opzionale. Senza credenziali non si dichiarerà una verifica live,
ma solo compatibilità con il contratto pubblico corrente.

### Criteri di completamento

- Sono presenti fixture per tutti i tool e per entrambe le origini contrattuali.
- Le fixture self-hosted provengono da dati sintetici reali.
- Le fixture Cloud sono chiaramente marcate come derivate dal contratto ufficiale.
- Nessuna fixture contiene dati sensibili.

---

## Fase 2 — Modelli Pydantic e input forti

### File principale

[`src/umami_mcp_server/models.py`](src/umami_mcp_server/models.py)

Il file può restare singolo finché le dimensioni rimangono contenute. Suddividerlo in un
package `models/` solo se input, output e helper diventano difficili da navigare.

### Modello base

Introdurre un modello comune:

```python
class UmamiModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
```

I campi extra devono essere accettati e conservati in serializzazione. Gli output schema MCP
continueranno quindi a mostrare `additionalProperties: true`, ma descriveranno i campi noti.

### Modelli di output

Definire almeno:

- `WebsiteUser`;
- `Website`;
- `WebsitePage`;
- `StatsValues`;
- `WebsiteStats`;
- `TimeSeriesPoint`;
- `PageviewsComparison`;
- `Pageviews`;
- `Metric`;
- `ExpandedMetric`;
- `ActiveVisitors`.

Contratti minimi:

- `WebsitePage`: `data`, `count`, `page`, `pageSize`;
- `Website`: `id`, `name`, `domain`; ownership, share e timestamp opzionali;
- `WebsiteStats`: `pageviews`, `visitors`, `visits`, `bounces`, `totaltime`, `comparison`;
- `Pageviews`: serie `pageviews` e `sessions`; `startDate`, `endDate` e `compare` opzionali;
- `Metric`: `x`, `y`;
- `ExpandedMetric`: `name`, `pageviews`, `visitors`, `visits`, `bounces`, `totaltime`;
- `ActiveVisitors`: `visitors`.

Usare `UUID`, `datetime`, `int` e tipi opzionali sulla base delle fixture. Non rendere
obbligatori campi di ownership non presenti in entrambi i contratti.

Per `get_metrics`, il tipo pubblico sarà `list[Metric | ExpandedMetric]`. MCP SDK v2
inserirà la lista nel wrapper strutturato `result`; non deve essere reintrodotto un
`list[dict[str, Any]]`.

### Input riusabili

Usare `Annotated`, `Field` e validator Pydantic per produrre vincoli e descrizioni nello
schema MCP:

- `WebsiteId = Annotated[UUID, Field(description=...)]`;
- `Page = Annotated[int, Field(ge=1, ...)]`;
- `PageSize = Annotated[int, Field(ge=1, le=100, ...)]`;
- `MetricLimit = Annotated[int, Field(ge=1, le=500, ...)]`;
- `MetricOffset = Annotated[int, Field(ge=0, le=10000, ...)]`;
- unità: `minute | hour | day | month | year`;
- confronto: `prev | yoy`.

Il tipo delle metriche v3 deve includere i valori supportati dall'API corrente:

```text
path, fullPath, entry, exit, referrer, domain, title, query,
event, tag, hostname, utmSource, utmMedium, utmCampaign,
utmContent, utmTerm, browser, os, device, screen, language,
country, city, region, distinctId, channel
```

Prima di finalizzare l'enum, confrontarlo con le fixture, la documentazione corrente e le
costanti della versione Umami v3 fissata per i test.

### Filtri v3

Completare `Filters` almeno con i filtri documentati mancanti:

- `language`;
- `event`;
- `distinct_id`, alias upstream `distinctId`;
- `utm_source`, alias `utmSource`;
- `utm_medium`, alias `utmMedium`;
- `utm_campaign`, alias `utmCampaign`;
- `utm_content`, alias `utmContent`;
- `utm_term`, alias `utmTerm`.

Convertire `segment` e `cohort` in `UUID | None`.

Serializzare le query con:

```python
filters.model_dump(mode="json", by_alias=True, exclude_none=True)
```

Non aggiungere parametri interni o non documentati di Umami v3.

### Timezone IANA

Validare la timezone con `zoneinfo.ZoneInfo`, convertendo `ZoneInfoNotFoundError` in errore di
input Pydantic. Aggiungere `tzdata` alle dipendenze runtime per garantire il database IANA
anche sui sistemi che non lo forniscono.

Lo schema deve restare una stringa con descrizione ed esempio, mentre la validazione avviene
prima di entrare nel corpo del tool.

### Range temporale

Mantenere esattamente il comportamento corrente:

| Input | Intervallo |
|---|---|
| nessuno | `now - 7 giorni .. now` |
| solo `end_at` | `end_at - 7 giorni .. end_at` |
| solo `start_at` | `start_at .. now` |
| entrambi | intervallo esplicito |

Preservare inoltre:

- datetime naive interpretati come UTC;
- conversione a millisecondi;
- rifiuto di `end_at <= start_at`.

Rendere il clock controllabile internamente nei test, senza esporlo nello schema MCP.

### Criteri di completamento

- Nessun tool pubblico usa output generici.
- Tutte le fixture vengono validate.
- Campi extra sono conservati.
- Input invalidi vengono respinti prima di qualsiasi HTTP.
- Gli schema MCP espongono vincoli, descrizioni, enum, UUID e output noti.

---

## Fase 3 — Client HTTP, autenticazione ed errori

### File principale

[`src/umami_mcp_server/umami_client.py`](src/umami_mcp_server/umami_client.py)

### Gerarchia di errori sicuri

Sostituire l'errore indistinto con categorie controllate:

- `UmamiAuthenticationError`;
- `UmamiRateLimitError`;
- `UmamiTimeoutError`;
- `UmamiNetworkError`;
- `UmamiUpstreamError`;
- `UmamiInvalidResponseError`.

Il testo pubblico delle eccezioni non deve contenere:

- body upstream;
- token, API key o password;
- header;
- URL completi con query;
- testo grezzo di eccezioni `httpx`;
- valori inclusi nelle `ValidationError` Pydantic.

Usare il logging standard Python, che su stdio finisce su stderr. Registrare soltanto:

- endpoint logico senza query;
- status code;
- numero del tentativo;
- classe dell'errore;
- location e tipo degli errori Pydantic con input escluso.

Non usare il logging MCP, deprecato nella revisione corrente.

### Validazione delle risposte

I metodi pubblici devono restituire tipi concreti:

```text
get_websites -> WebsitePage
get_stats -> WebsiteStats
get_pageviews -> Pageviews
get_metrics -> list[Metric | ExpandedMetric]
get_active -> ActiveVisitors
```

Validare nel client, prima di restituire il risultato al tool, tramite `model_validate` o
`TypeAdapter`. Questo è importante perché affidare la validazione al convertitore MCP
produrrebbe errori dopo il ritorno del tool e potrebbe esporre dettagli della risposta.

Convertire in `UmamiInvalidResponseError`:

- JSON malformato;
- risposta non JSON quando è atteso JSON;
- payload incompatibile con il modello;
- login concluso senza un token stringa valido.

Chiudere sempre ogni `httpx.Response` in `finally`.

### Login concorrente

Aggiungere un `asyncio.Lock` dedicato al token.

`_ensure_token()` deve:

1. uscire immediatamente in modalità API key;
2. restituire il token già presente;
3. acquisire il lock se il token manca;
4. controllare nuovamente il token dopo l'acquisizione;
5. eseguire un solo login;
6. assegnare il token soltanto dopo una risposta valida.

Richieste iniziali concorrenti devono quindi causare un solo `POST /auth/login`.

Il login POST non usa il retry generico degli endpoint analytics. Dopo un errore, una nuova
tool call potrà tentare nuovamente il login.

### Refresh concorrente dopo `401`

Ogni invio deve conservare il token effettivamente usato. Quando una richiesta login-mode
riceve `401`:

1. verificare che non abbia già usato il refresh consentito;
2. acquisire il lock;
3. invalidare il token soltanto se coincide ancora con quello della richiesta fallita;
4. se un'altra coroutine ha già installato un token nuovo, riutilizzarlo;
5. altrimenti effettuare un solo nuovo login;
6. ripetere la richiesta se rimane budget analytics.

Questo impedisce a un `401` tardivo di cancellare un token appena rinnovato e garantisce un
solo refresh anche con più `401` concorrenti.

Comportamenti speciali:

- API key + `401`: fallimento immediato, nessun refresh;
- `403`: errore di autenticazione/autorizzazione non rinnovabile;
- secondo `401` nella stessa richiesta logica: errore controllato senza nuovo refresh.

### Retry

Definire costanti esplicite, ad esempio:

```text
MAX_ATTEMPTS = 3
BASE_RETRY_DELAY_S = 0.5
MAX_RETRY_DELAY_S = 60.0
```

Ritentare soltanto richieste idempotenti e, nella P1, soltanto i `GET` esposti dal client.
Cause ritentabili:

- `httpx.TransportError`;
- timeout, esposti poi come categoria distinta se esauriti;
- `429`;
- `500`, `502`, `503`, `504`.

Non ritentare:

- altri `4xx`;
- `501`, `505` e status non transitori;
- errori JSON/Pydantic;
- login fallito;
- autenticazione API key fallita.

Il delay di fallback usa exponential backoff con full jitter:

```text
uniform(0, min(BASE_RETRY_DELAY_S * 2**retry_index, MAX_RETRY_DELAY_S))
```

Per `429`, leggere `Retry-After` sia come secondi sia come HTTP-date:

- se valido, ha precedenza;
- applicare il limite di 60 secondi;
- se assente o invalido, usare il backoff con jitter.

Non chiamare mai `sleep()` dopo il terzo tentativo. Non intercettare `CancelledError` e
mantenere cancellabili le attese.

Per test deterministici, rendere iniettabili internamente sleep, random e clock, senza
aggiungere configurazione utente.

### Criteri di completamento

- Un solo login iniziale con chiamate concorrenti.
- Un solo refresh per token scaduto con `401` concorrenti.
- Massimo 3 invii analytics per richiesta logica.
- Nessuna sleep dopo l'ultimo invio.
- Nessun body o secret nei risultati MCP e nei log.
- Errori pubblici distinti e prevedibili.

---

## Fase 4 — Lifespan MCP e tool

### File principale

[`src/umami_mcp_server/server.py`](src/umami_mcp_server/server.py)

### AppContext e lifespan

Aggiungere un contesto tipizzato:

```python
@dataclass(frozen=True, slots=True)
class AppContext:
    umami_client: UmamiClient
```

Creare un lifespan asincrono che:

1. legge e valida `get_settings()` allo startup;
2. crea un solo `UmamiClient`;
3. restituisce `AppContext`;
4. chiude il client in `finally`.

Costruire il server come `MCPServer[AppContext](..., lifespan=_lifespan)`.

Con MCP SDK v2.0 installato, gli import corretti sono:

```python
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
```

I tool ricevono `ctx: Context[AppContext]` e accedono al client tramite:

```python
ctx.request_context.lifespan_context.umami_client
```

Il parametro context viene riconosciuto dall'SDK e non compare nello schema input.

Eliminare `_umami_client()` e tutti gli `async with` per tool. `run()` non deve creare un
secondo client; la configurazione viene validata entrando nel lifespan.

### Firme e descrizioni dei tool

Usare i modelli e i tipi vincolati della Fase 2:

```text
get_websites -> WebsitePage
get_stats -> WebsiteStats
get_pageviews -> Pageviews
get_metrics -> list[Metric | ExpandedMetric]
get_active -> ActiveVisitors
```

Aggiungere descrizioni Pydantic a ogni parametro e correggere la descrizione di
`get_websites`: restituisce una pagina, non tutti i website.

Le descrizioni di `get_stats`, `get_pageviews` e `get_metrics` devono documentare le quattro
regole del range temporale di sette giorni.

### Criteri di completamento

- Una sola istanza `UmamiClient` e `httpx.AsyncClient` per lifespan.
- Chiusura esattamente una volta allo shutdown, anche in caso di errore.
- Tutti i tool condividono lo stesso client.
- Il context non appare nello schema MCP.
- Gli output schema sono descrittivi e non generici.

---

## Fase 5 — Test

## `tests/test_models.py`

Aggiungere test per:

- quattro combinazioni del range temporale;
- clock deterministico;
- datetime naive interpretati come UTC;
- range nullo o invertito;
- timezone IANA valida e invalida;
- UUID di website, segment e cohort;
- limiti numerici;
- unità `minute`;
- enum completo delle metriche;
- filtri v3 e alias upstream;
- validazione di tutte le fixture Cloud e self-hosted;
- conservazione dei campi extra;
- rifiuto di payload strutturalmente incompatibili.

## `tests/test_umami_client.py`

Aggiungere test per:

- login iniziale e bearer token;
- richieste concorrenti con un solo login;
- `401`, refresh e successo;
- `401` concorrenti con un solo refresh;
- secondo `401` senza loop di refresh;
- API key `401` senza retry;
- `403` senza refresh;
- esattamente tre invii per rete, timeout, `429` e `5xx` transitori;
- nessuna sleep dopo l'ultimo tentativo;
- nessun retry per `400`, `404`, `501`;
- `Retry-After` numerico e HTTP-date;
- fallback su `Retry-After` invalido;
- cap del delay a 60 secondi;
- backoff e jitter deterministici;
- risposta non JSON;
- payload JSON non conforme;
- stringhe sensibili nel body assenti da eccezioni e `caplog`;
- chiusura delle response e dell'`AsyncClient`.

Per le race usare handler asincroni con eventi/barriere, evitando test dipendenti dal timing.

## `tests/test_server.py`

Il nuovo lifespan richiederà fake settings o un client fittizio prima di entrare in
`Client(server)`. Gestire esplicitamente la cache di `get_settings()` nei test.

Aggiungere test per:

- una sola costruzione del client per lifespan;
- riuso tra tool differenti;
- `aclose()` una sola volta allo shutdown;
- chiusura anche dopo eccezione;
- tool call concorrenti;
- context escluso dallo schema;
- vincoli numerici nello schema;
- `website_id` con `format: uuid`;
- unità ed enum metriche completi;
- output schema basati sui modelli;
- `additionalProperties: true`;
- input invalidi respinti senza richieste HTTP;
- errori upstream sanitizzati come errori tool;
- ordine deterministico e compatibilità client legacy già esistenti.

## Test Cloud live opzionale

Aggiungere `tests/test_live_cloud.py`, marcato `live` e saltato salvo presenza di:

```text
UMAMI_LIVE_CLOUD_API_KEY
UMAMI_LIVE_CLOUD_WEBSITE_ID
```

Opzionalmente accettare `UMAMI_LIVE_CLOUD_API_BASE`, con default Cloud corrente. Il test:

- usa soltanto endpoint read-only;
- chiama tutti i tool, incluse metriche expanded;
- valida i modelli;
- non stampa payload o credenziali;
- non è richiesto dalla CI ordinaria.

Registrare il marker `live` in `pyproject.toml`.

### Verifiche finali della suite

```bash
uv run ruff format . --check
uv run ruff check .
uv run pyright
uv run pytest
```

---

## Fase 6 — Settings e documentazione

### `src/umami_mcp_server/settings.py`

Mantenere:

- Cloud autenticato soltanto con API key;
- self-hosted autenticato con username/password;
- default Cloud `https://api.umami.is/v1`.

Aggiornare descrizioni ed errori per dichiarare self-hosted v3.x e mostrare la root corretta
`https://host.example/api`. Non introdurre rilevamento o adattamento v1/v2.

Valutare come errore di configurazione la presenza contemporanea di API key e
username/password, invece dell'attuale precedenza implicita alla API key.

### `README.md`

Aggiornare:

- descrizione: Cloud corrente e self-hosted v3.x;
- support matrix: v1 esclusa, v2 futura e separata;
- spiegazione della differenza tra `/v1` Cloud e Umami self-hosted v1;
- requisito Python `3.11+`;
- comando `uvx umami-mcp-server`;
- esempio self-hosted con `/api`;
- JSON valido, senza trailing comma;
- `enabled` dentro l'oggetto server MCP corretto;
- natura paginata di `get_websites`;
- limiti numerici;
- metric types e filtri v3;
- timezone IANA e unità `minute`;
- semantica completa del range di sette giorni;
- categorie di errori sicuri.

---

## Fase 7 — Versione, CI e packaging

### `pyproject.toml`

- impostare `version = "0.2.0"`;
- mantenere `requires-python = ">=3.11"`;
- aggiungere `tzdata` alle dipendenze;
- registrare il marker pytest `live`;
- rigenerare `uv.lock`.

### `pyrightconfig.json`

Impostare `pythonVersion` a `3.11`, in modo che il type checking verifichi la baseline minima
supportata. `.python-version` può restare `3.13` come versione di sviluppo locale: non è una
dichiarazione del requisito minimo.

### `.github/workflows/ci.yml`

Mantenere la matrice Python 3.11–3.14 e aggiungere un job wheel smoke su Python 3.11:

1. checkout;
2. `uv build --no-sources`;
3. creare un virtualenv temporaneo pulito;
4. installare direttamente il wheel con `uv pip install`, senza `uv sync` e senza usare
   `uv.lock`;
5. importare il package;
6. verificare l'entry point `umami-mcp-server` senza lasciare il server bloccato su stdio;
7. controllare con `importlib.metadata` versione e dipendenze del wheel.

### `.github/workflows/publish.yml`

Prima del publish:

- verificare che il tag coincida con `project.version`;
- costruire in un runner pulito;
- verificare metadata e installabilità del wheel;
- pubblicare soltanto gli artefatti appena generati.

Eliminare gli artefatti locali obsoleti da `dist/` e ricostruirli come `0.2.0` durante la
preparazione della release. `dist/` resta ignorata e non deve essere committata.

---

# Ordine consigliato dei commit

1. Fixture contrattuali v3 e relativi test di parsing inizialmente failing.
2. Modelli output, filtri, tipi input, timezone e range temporale.
3. Gerarchia errori, parsing tipizzato e sanitizzazione nel client.
4. Lock login, refresh concorrente su `401` e retry.
5. `AppContext`, lifespan e conversione dei tool.
6. Test MCP completi e test live opzionale.
7. README, settings e support matrix.
8. Versione `0.2.0`, lockfile, wheel smoke e hardening del publish.

Ogni commit deve lasciare il prodotto funzionante end-to-end e la suite verde; evitare di
accumulare modelli o refactoring non ancora usati dai tool.

---

# Criteri finali di accettazione

## Compatibilità

- Cloud corrente e self-hosted v3.x soddisfano gli stessi contratti pubblici.
- README dichiara chiaramente il perimetro di supporto.
- Non esistono adapter, fallback o branching v2.

## Lifespan e autenticazione

- Una sola istanza HTTP per lifespan MCP.
- Chiusura esattamente una volta allo shutdown.
- Un solo login per richieste iniziali concorrenti.
- Un solo refresh per token scaduto anche con `401` concorrenti.
- Massimo un refresh e tre invii analytics per richiesta logica.

## Input

- UUID, limiti, timezone, unità e metriche invalidi vengono rifiutati prima dell'HTTP.
- Tutti i filtri v3 documentati vengono serializzati con i nomi upstream corretti.
- Le quattro regole temporali producono il range previsto.
- Lo schema MCP contiene descrizioni comprensibili per ogni parametro.

## Output

- Nessun tool pubblico restituisce `dict[str, Any]` o `list[dict[str, Any]]`.
- Tutti gli output vengono validati prima della conversione MCP.
- I campi extra Cloud/v3 vengono accettati e conservati.
- Gli output schema descrivono campi e tipi reali.
- Errori JSON o Pydantic diventano messaggi controllati.

## Retry e sicurezza

- Tre invii totali, non tre retry.
- Nessuna attesa dopo l'ultimo tentativo.
- `Retry-After` viene interpretato e rispettato entro il limite definito.
- Solo rete, timeout, `429` e `5xx` transitori idempotenti vengono ritentati.
- Nessun secret, body, header o eccezione grezza compare nei risultati MCP o nei log.

## Release

- Test, Ruff e Pyright passano su Python 3.11–3.14.
- Il wheel `0.2.0` si installa in un ambiente pulito senza lockfile.
- Metadata, entry point, README, tag e artefatti riportano tutti `0.2.0`.

---

# Rischi noti e mitigazioni

- **Drift Cloud:** `extra="allow"` tollera campi aggiunti, non rimozioni o cambi di tipo.
  Mantenere fixture datate e test live opzionale.
- **Differenze tra patch v3:** non rendere obbligatori campi di ownership non confermati da
  entrambe le fixture.
- **Race sul token:** invalidare solo il token effettivamente fallito, sotto lock.
- **`Retry-After` eccessivo:** applicare il cap di 60 secondi e mantenere cancellabile il task.
- **Leak da Pydantic:** non usare `str(ValidationError)` nei messaggi o nei log; escludere gli
  input dai dettagli diagnostici.
- **Database IANA assente:** installare `tzdata` oltre a usare `zoneinfo`.
- **Drift MCP SDK:** `mcp>=2,<3` consente minor release; mantenere test su import, context e
  schema MCP.
- **Fixture sensibili:** acquisire solo dati sintetici e revisionare manualmente i file prima
  del commit.
- **Artefatti locali obsoleti:** costruire sempre wheel e sdist in una directory pulita per
  smoke e publish.

# File principali coinvolti

- `src/umami_mcp_server/server.py` — lifespan, `AppContext`, tool e schema MCP.
- `src/umami_mcp_server/umami_client.py` — HTTP, autenticazione, retry, errori e parsing.
- `src/umami_mcp_server/models.py` — input, output, filtri e tempo.
- `src/umami_mcp_server/settings.py` — perimetro Cloud/self-hosted v3.
- `tests/test_models.py` — contratti Pydantic e input.
- `tests/test_umami_client.py` — concorrenza, retry e sanitizzazione.
- `tests/test_server.py` — lifespan e superficie MCP.
- `tests/fixtures/` — contratti Cloud e self-hosted v3.
- `README.md` — support matrix e utilizzo.
- `pyproject.toml`, `uv.lock`, `pyrightconfig.json` — runtime e tooling.
- `.github/workflows/ci.yml` — suite e smoke wheel.
- `.github/workflows/publish.yml` — coerenza e pubblicazione `0.2.0`.
