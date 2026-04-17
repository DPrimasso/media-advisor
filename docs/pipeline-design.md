# Pipeline Design — Media Advisor

_Aggiornato: aprile 2026_

---

## Pipeline analisi claim (singolo video)

Il punto di ingresso è `src/media_advisor/pipeline/analyze_v2.py`.

```
transcript JSON
      │
      ▼
cleaner.py          → rimuove rumore (filler words, ripetizioni, artefatti ASR)
      │
      ▼
segmenter.py        → divide il transcript in segmenti tematici coerenti
      │
      ▼
extractor.py        → PydanticAI + gpt-4o-mini → lista Claim strutturati per segmento
      │
      ▼
aggregator.py       → deduplicazione + merge claim simili, raggruppamento in Theme
      │
      ▼
specificity.py      → filtra claim troppo generici o vaghi (score < threshold)
      │
      ▼
entity_normalizer.py → normalizza nomi giocatori/squadre (alias → canonical)
      │
      ▼
summarizer.py       → AI summary 2-3 frasi in italiano del video
      │
      ▼
analysis/<channel_id>/<video_id>.json
```

### Claim schema

```python
class Claim(BaseModel):
    claim_id: str          # UUID
    target_entity: str     # es. "Lukaku", "Napoli"
    entity_type: str       # player | team | coach | transfer | other
    dimension: str         # injury | form | transfer | tactics | media | contract | ...
    claim_type: str        # FACT | OPINION | PREDICTION
    stance: str            # POS | NEG | NEUTRAL
    intensity: int         # 1-3
    modality: str          # CERTAIN | PROBABLE | POSSIBLE | RUMOR
    claim_text: str        # frase completa in italiano
    evidence_quotes: list[EvidenceQuote]

class EvidenceQuote(BaseModel):
    quote_text: str
    start_sec: float
    end_sec: float
```

### Output finale (VideoAnalysis)

```json
{
  "video_id": "abc123",
  "analyzed_at": "2026-04-15T12:00:00Z",
  "metadata": {
    "title": "...",
    "author_name": "Azzurro Fluido",
    "published_at": "2026-04-01"
  },
  "summary": "Riassunto in 2-3 frasi...",
  "topics": [
    { "name": "calciomercato", "relevance": "high" },
    { "name": "tattica", "relevance": "medium" }
  ],
  "claims": [ ... ]
}
```

---

## Pipeline mercato (calciomercato tips)

Il punto di ingresso è `src/media_advisor/mercato/analyzer.py`.

```
transcript JSON
      │
      ▼
extractor.py        → PydanticAI + gpt-4o-mini → lista MercatoTip raw
      │
      ▼
(corroborator.py)   → confronto incrociato tra tip di canali diversi
      │
      ▼
mercato/tips/<channel_id>/<video_id>.json
      │
      ▼
aggregator.py       → merge + rebuild mercato/index.json
      │
      ▼
verifier.py         → confronto vs transfers.json → aggiorna outcome
```

### MercatoTip schema

```python
class OutcomeValue(str, Enum):
    non_verificata = "non_verificata"
    confermata = "confermata"
    smentita = "smentita"
    parziale = "parziale"

class MercatoTip(BaseModel):
    tip_id: str              # UUID
    video_id: str
    channel_id: str
    player_name: str
    player_slug: str         # lowercase, no accents
    from_club: str | None
    to_club: str | None
    fee_mention: str | None  # testo libero
    confidence: str          # high | medium | low
    outcome: OutcomeValue
    mentioned_at: datetime | None
    quote_text: str
    quote_start_sec: float
    quote_end_sec: float
    corroborated_by: list[str]   # channel_id di canali che corroborano
```

### Transfer DB schema

```json
{
  "transfers": [
    {
      "player_name": "Osimhen",
      "player_slug": "osimhen",
      "from_club": "Napoli",
      "to_club": "Galatasaray",
      "fee_eur": 75000000,
      "transfer_date": "2024-08-29",
      "season": "2024-25",
      "source": "transfermarkt",
      "transfermarkt_id": "289487"
    }
  ]
}
```

---

## Batch run-list

`src/media_advisor/run_pipeline.py` — `run_from_list()`:

1. Per ogni canale in `channels.json`:
   - Legge la video list `channels/<channel_id>.json`
   - Per ogni video non ancora analizzato (no `analysis/<channel>/<video>.json`):
     - Scarica transcript via `transcript_api/client.py` se non esiste
     - Lancia `analyze_v2.py`
     - Scrive `analysis/<channel>/<video>.json`
2. Se il canale ha `mercato_channel: true`, lancia anche `mercato/analyzer.py`
3. Al termine ricostruisce `mercato/index.json`

---

## Fetch nuovi video

`src/media_advisor/fetch.py` — `run_fetch_new_videos()`:

1. Legge `channels.json` e le fetch rules
2. Per ogni canale chiama TranscriptAPI (lista video da channel_url)
3. Applica filtri: `last_n`, `title_contains`, `exclude_title_contains`, `exclude_live`
4. Scrive i nuovi video in `channels/pending.json`
5. L'utente approva da InboxView (o `media-advisor auto-update` li approva tutti)

---

## Transcript API client

`src/media_advisor/transcript_api/client.py`:

- Client async httpx con retry (backoff esponenziale)
- Endpoint: `GET /transcript?video_id=<id>` → `TranscriptResponse`
- Salva in `transcripts/<channel_id>/<video_id>.json`
- Richiede `TRANSCRIPT_API_KEY` in `.env`
