# Avvio della dashboard

> **Scopo:** spiega come installare le dipendenze e avviare la dashboard, con gli argomenti da riga di comando e le variabili di `.env`. Da leggere per far partire l'app su una macchina nuova.

## Cosa serve prima di avviare

1. **Python 3.12** (la versione dell'ambiente di sviluppo, `.venv`).
2. **La cartella `data/`** nella radice della repo. Non è in git (è nel `.gitignore`), quindi va ottenuta a parte. Senza di essa l'app non parte, perché `utils.py` apre le tabelle all'import. Deve contenere:
   - `projects_uncase.lance`, `participants.lance`, `deliverables.lance`, `publications.lance`
   - `bge-m3-onnx/` (modello di embedding per il testo libero)
   - `topic2hier.json`, `organisations.json`
   - `project_graphs/`

   Il ruolo di ciascun elemento è in [Struttura dei dati](../01-panoramica/struttura-dati.md).
3. **Un file `.env`** (opzionale per l'avvio, vedi sotto).

## Installazione

Dalla radice della repo:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Il `requirements.txt` è **uno solo** e vale sia per la dashboard sia per la pipeline di aggiornamento (le versioni sono compatibili, quindi basta un ambiente). Per la dashboard bastano le librerie della sezione `--- dashboard ---`, ma installare tutto non crea problemi; l'installazione completa è però più pesante (include BERTopic, docling e altre). Il passo in più `nltk.download('stopwords')` serve solo alla pipeline: vedi [Eseguire l'aggiornamento dei dati, sezione P1](../03-aggiornamento-dati/eseguire-update-db.md#p1-preparare-lambiente).

## Avvio

Sempre dalla radice della repo (i percorsi `data/` e `assets/` sono relativi alla cartella corrente):

```bash
python app.py
```

Con le opzioni di default l'app risponde su `http://localhost:8050/research_intelligence/query`.

Il primo avvio può richiedere un po' di tempo: all'import si aprono le tabelle e si calcolano i contatori della homepage. Il modello di embedding si carica invece **alla prima ricerca con testo libero**, non all'avvio, quindi quella prima ricerca è più lenta delle successive.

## Argomenti da riga di comando

Gli argomenti sono letti da `utils.py` con `argparse`.

| Argomento | Default | Significato |
|---|---|---|
| `--path` | `/research_intelligence/` | Percorso base dell'app. Tutte le pagine vivono sotto questo prefisso. |
| `--port` | `8050` | Porta su cui il server ascolta. |

Esempio:

```bash
python app.py --path /research_intelligence/ --port 8050
```

Note:

- Il valore di `--path` viene normalizzato: se manca la `/` iniziale o finale, viene aggiunta. `ri` diventa `/ri/`.
- Il server ascolta su `0.0.0.0` (tutte le interfacce) con `debug=False`. Entrambi sono scritti in `app.py`, non configurabili da riga di comando.
- Le pagine sono `<path>query` (ricerca) e `<path>concept` (tassonomia).
- Il percorso base serve quando l'app sta dietro un reverse proxy che la espone sotto un prefisso. Il prefisso del proxy e `--path` devono coincidere.
- `argparse` gira **all'import di `utils.py`**: qualunque script che importa `utils` (per esempio un test o un notebook) eredita questi argomenti e può fallire se riceve altri parametri.

## File `.env`

`utils.py` carica `.env` dalla cartella da cui lanci l'app (con `python-dotenv`). Il file **non è in git**.

| Variabile | Uso |
|---|---|
| `EXPLAINABILITY_BASE_URL` | Indirizzo del servizio LLM di relevance |
| `EXPLAINABILITY_API_KEY` | Chiave per quel servizio |

Esempio di file:

```
EXPLAINABILITY_BASE_URL=http://<host>:<porta>
EXPLAINABILITY_API_KEY=<chiave>
```

**Stato attuale:** le due variabili vengono lette ma oggi **non influiscono sul comportamento**. `scripts/_explainability_api.py` usa un URL scritto nel codice (`http://research-llm-api-matita:8060/v1/project/relevance`) e l'intestazione con la chiave è commentata. Se `.env` manca, l'app parte lo stesso (le variabili valgono `None`).

Se il servizio cambia indirizzo, oggi va modificato l'URL nel codice. 

## Cosa succede se qualcosa manca

| Sintomo | Causa probabile |
|---|---|
| Errore all'avvio su una tabella LanceDB (`Table ... was not found`) | `data/` mancante o incompleta, oppure lanciata da un'altra cartella. Se la cartella `.lance` è stata scaricata da browser, controlla che i file `_versions/*.manifest` non siano diventati `*.manifest.appcache`: rimuovi il suffisso. |
| Errore su `data/bge-m3-onnx` alla prima ricerca con testo libero | Cartella del modello mancante o incompleta. |
| La ricerca con testo libero non restituisce nulla | Vedi [Struttura dei dati](../01-panoramica/struttura-dati.md#due-regole-che-la-dashboard-richiede): l'indice vettoriale su `projects_uncase.vector` deve essere assente. |
| Il pulsante "Why is this relevant?" non risponde | Il servizio LLM non è raggiungibile dal server (vedi sopra). |
| `unrecognized arguments` | Argomenti non previsti passati ad `app.py` (o a un modulo che importa `utils`). |

## Deploy

> **Da completare:** sezione di deploy per il nuovo server.

## Pagine collegate

- [Architettura](../01-panoramica/architettura.md): come sono organizzati codice e dati.
- [Aggiornamento dei dati](../03-aggiornamento-dati/eseguire-update-db.md): come si produce una `data/` aggiornata.
