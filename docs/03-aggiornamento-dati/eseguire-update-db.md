# Eseguire l'aggiornamento dei dati

> **Scopo:** dà la visione d'insieme di un aggiornamento dei dati con un nuovo export CORDIS: cosa fare prima, cosa fa `update_db.py` e cosa fare dopo. Da leggere per primo: i dettagli di ogni passo stanno nelle pagine collegate.

## Quando aggiornare

- Quando CORDIS pubblica un nuovo export con progetti che non sono ancora nel database.
- **La frequenza va decisa da chi gestisce la piattaforma.** Il consiglio è di aggiornare ogni **4-6 mesi**, così da avere abbastanza progetti nuovi su cui rifare il topic modeling.
- Se l'export non contiene progetti nuovi, `update_db.py` si ferma subito ("There are no new projects. Aborting session.").

## Quanto tempo serve

| Passo | Tempo |
|---|---|
| Embedding (Specter2 e bge-m3) | Da circa **un'ora** (per entrambi) a **più ore**, a seconda della macchina su cui girano |
| Revisione dei topic | Non più di **mezz'ora** per il revisore (dipende dal numero di candidati); l'aggiornamento non la aspetta, il foglio si applica dopo con un secondo lancio |

## Cosa viene modificato

Gli script scrivono **direttamente** nella cartella `data/` usata dalla dashboard (e in `assets/treemap.json`): non serve copiare file a mano. Per questo conviene fare prima il backup (vedi più sotto).

| Cosa | Modificato da |
|---|---|
| `data/projects_uncase.lance` | step 1, 2 e 3 di `update_db.py`; `--review` (topic dei progetti del foglio e dei progetti vecchi che passano a topic nuovi) |
| `data/participants.lance` | step 2; `--review` (stessi progetti) |
| `data/deliverables.lance` | step 3 |
| `data/publications.lance` | **mai** (step 4 non ancora implementato) |
| `data/organisations.json` | step 2 |
| `data/project_graphs/` | step 2 e `--review` |
| `data/specter2.parquet` | step 1 |
| `data/old_topic_model/` e `data/topic2hier.json` | `--review` (solo se il foglio crea topic nuovi) |
| `new_data/topic_review_<data>.xlsx` | step 1 (foglio da compilare, se ci sono candidati a topic nuovi) |
| `assets/treemap.json` | fine dello step 1; `--review` |
| `assets/dmp_for_dash.html` | **mai** (da completare) |

## Schema generale

```
PRIMA                                     update_db.py                      DOPO
1. Ambiente                               step 1  progetti + topic          1. Controlli
2. Export CORDIS                          step 2  partecipanti + grafi      2. Riavviare la dashboard
3. Estrazione deliverables (da completare) step 3  deliverables             3. Parti statiche
4. Embedding                              step 4  publications (da compl.)  4. Rotazione programmi quadro
5. settings.config                        step 5  indici + treemap
6. Backup
```

---

## Passi preliminari

Tutti i comandi si lanciano **da dentro `data_update/`**: i percorsi sono relativi alla cartella corrente.

### P1. Preparare l'ambiente

La pipeline usa lo stesso `requirements.txt` della dashboard (nella radice della repo), e quindi lo stesso ambiente Python. `transformers` è fissato a 4.57.6 perché lo richiede `adapters` (usato per Specter2); la dashboard funziona con la stessa versione.

**Requisiti**

- **Python 3.12** (la versione con cui la pipeline è stata usata).
- **Connessione a internet al primo uso**: i modelli si scaricano da Hugging Face (`BAAI/bge-m3`, `allenai/specter2_base` e l'adapter `allenai/specter2`) e restano nella cache (`~/.cache/huggingface`). Servono circa **5 GB** di disco.
- **Una GPU aiuta molto** per gli embedding: `extract_embedding.py` usa in ordine MPS (Mac con chip Apple), CUDA, e solo in mancanza CPU. Su CPU i tempi sono molto più lunghi.

**Installazione** (dalla radice della repo; se l'ambiente della dashboard esiste già, basta riattivarlo e rilanciare `pip install -r requirements.txt`):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c "import nltk; nltk.download('stopwords')"
```

- L'ambiente sta in `.venv`, che il `.gitignore` esclude dal versionamento.
- L'installazione è lunga e pesante (include torch, docling e altre librerie).
- Il download di `stopwords` serve a `extract_topic.py` per la pulizia del testo dei topic.
- Su una macchina con GPU NVIDIA può essere necessario installare prima la versione di `torch` adatta alla propria versione di CUDA, seguendo le istruzioni di PyTorch, e poi il resto.

**Verifica** (con l'ambiente attivo, da `data_update/`):

```bash
python -c "import adapters, bertopic, FlagEmbedding, lancedb, hdbscan, umap, openpyxl; from nltk.corpus import stopwords; stopwords.words('english'); print('ok')"
```

Deve stampare `ok`. Un `ModuleNotFoundError` indica un pacchetto mancante; un `LookupError` di nltk indica che `stopwords` non è stato scaricato.

**Prima di ogni comando della pipeline**: attivare l'ambiente (`source .venv/bin/activate` dalla radice della repo) e poi spostarsi in `data_update/`.

**File `.env` (solo per l'estrazione dei deliverables).** Lo script `legacy_extract_deliverables.py` legge da `.env` la chiave `FEATHERLESS_API_KEY` (servizio LLM usato per estrarre gli autori) e `INDEX`. `update_db.py` e `compute_embeddings.py` non lo usano. Vedi P3 (da completare).

**Dati necessari**: la pipeline lavora sulla cartella `data/` nella radice della repo (percorso `../data` visto da `data_update/`). Deve esistere, con le tabelle e i file elencati in [Avvio della dashboard](../02-dashboard/avvio-dashboard.md), più `data/old_topic_model/`, `data/specter2.parquet` e `data/topic2hier.json`.

### P2. Scaricare l'export CORDIS

Si scarica da CORDIS (<https://cordis.europa.eu/projects>, sezione "Download projects as open data"), si decomprime in `data_update/new_data/<nome-cartella>` e si scrive il nome della cartella in `settings.config`:

```ini
[paths]
new_data_folder_name = new_data/2026-10-15
```

Sono supportati sia il vecchio formato (`project.json`, `organization.json`, ...) sia quello con un file per progetto (`project-rcn-*.json`), riconosciuto in automatico. **Solo il secondo permette di aggiornare i deliverables.** Dettagli sui formati: [Struttura dei dati](../01-panoramica/struttura-dati.md#formati-dellexport-cordis).

### P3. Estrarre i deliverables (da completare)

È necessario lanciare lo script `extract_deliverables`, che estrae titolo e autori dei deliverables dai PDF.

> **Da completare.** Oggi nella repo c'è solo la vecchia versione, `data_update/legacy_extract_deliverables.py`, tenuta come riferimento. Lo step 3 di `update_db.py` **non legge il risultato dell'estrazione**: scrive titoli e link presi dall'export e conserva solo gli autori già presenti nella tabella. I deliverables nuovi hanno quindi `authors = "{}"` finché l'estrazione non viene integrata.

### P4. Calcolare gli embeddings

Per ogni progetto nuovo servono due embedding, calcolati prima con `compute_embeddings.py` (da `data_update/`, ambiente attivo) e salvati in file parquet. Si lanciano uno dopo l'altro:

```bash
python compute_embeddings.py --model specter2 --source new
python compute_embeddings.py --model bge --source new
```

| Modello | A cosa serve | Dimensione |
|---|---|---|
| `specter2` | Assegnare i topic ai progetti nuovi; viene aggiunto anche a `data/specter2.parquet` | 768 |
| `bge` (bge-m3) | Ricerca semantica della dashboard; diventa la colonna `projects_uncase.vector` | 1024 |

**Come funziona**

- `--source new` calcola gli embedding dei progetti dell'export (`new_data_folder_name` in `settings.config`) che **non sono ancora in `projects_uncase`**: sono gli stessi che aggiungerà `update_db.py`.
- Il testo embeddato è titolo e obiettivo, in minuscolo e con gli spazi normalizzati (massimo 512 token per Specter2, 8192 per bge-m3).
- Il file prodotto è un parquet con due colonne: `projectID` (int32) e `vector` (float32). Ogni vettore è legato al proprio `projectID`, non alla posizione nel file.
- Il file di output di default è `new_data/<modello>_<nome-cartella-export>.parquet`, per esempio `new_data/specter2_2026-10-15.parquet` e `new_data/bge_2026-10-15.parquet`. Si può cambiare con `--out`.
- La scrittura è sicura: il file viene scritto con un nome temporaneo e poi rinominato, quindi un'interruzione non lascia un file a metà.
- Se non ci sono progetti nuovi stampa `No projects to embed.` ed esce.
- All'inizio stampa il numero di progetti e il dispositivo usato, alla fine `N embeddings written to <file>`. Il dispositivo è scelto in automatico: MPS (Mac con chip Apple), poi CUDA, poi CPU.

**Opzioni utili**

| Opzione | Effetto |
|---|---|
| `--device mps\|cuda\|cpu` | Forza il dispositivo |
| `--batch-size N` | Dimensione dei blocchi per Specter2 (default 32); da abbassare se manca memoria |
| `--out FILE` | Cambia il file di output |
| `--limit N` | Solo i primi N progetti, per un test rapido. **Il file prodotto non va usato per l'aggiornamento vero**: `update_db.py` si ferma se un progetto nuovo non ha il suo embedding |
| `--source db` | Calcola gli embedding di **tutti** i progetti del db invece che dei nuovi (serve per ricostruire `data/specter2.parquet`, vedi [Review dei topic](review-topic.md#210-archivio-degli-embedding-specter2)) |

**Dopo il calcolo**: scrivere i due file in `settings.config`:

```ini
[paths]
bge_embedding_file = new_data/bge_2026-10-15.parquet
specter2_embedding_file = new_data/specter2_2026-10-15.parquet
```

Se un percorso è lasciato vuoto, `update_db.py` calcola quell'embedding da solo; calcolarli prima è preferibile, perché permette di scoprire subito un problema e di non rifare il calcolo se `update_db.py` si interrompe.

**Controlli che fa `update_db.py` sui file**

Si ferma con un messaggio se: il file non esiste o non è un parquet, ci sono `projectID` ripetuti, manca l'embedding di un progetto nuovo, la dimensione di bge-m3 non coincide con quella di `projects_uncase.vector`, oppure il file è un `.npy` (i vecchi file senza `projectID` non sono più accettati). I progetti in più nel parquet vengono ignorati.

Questo succede, per esempio, se gli embedding sono stati calcolati su un'altra cartella dell'export o con `--limit`: va rifatto il calcolo sull'export giusto.

**Primo uso**: i modelli (`BAAI/bge-m3`, circa 4,3 GB, e `allenai/specter2_base`) si scaricano da Hugging Face, quindi il primo lancio è più lento e serve internet.

In passato è stato verificato che gli embedding ricalcolati coincidono con quelli già nel db (Specter2: similarità coseno 1,0; bge-m3: in media 0,9993, minimo 0,994). Per questo si possono mescolare vettori vecchi e nuovi nello stesso db.

### P5. Controllare `settings.config`

Oltre ai percorsi sopra, la sezione `[topics]` contiene i parametri dell'assegnazione dei topic (soglia di similarità 0,92, dimensione minima dei cluster, file Excel della revisione, bonus per i topic nuovi). I valori attuali vanno bene nella maggior parte dei casi. La sezione `[columns]` serve solo per il vecchio formato dell'export.

### P6. Fare il backup

Il backup di `data/` va fatto **a mano** prima di ogni aggiornamento.

La pipeline ne fa solo alcuni da sola, in `data/backups/`, e **solo quando `--review` modifica il modello**:

- il modello dei topic (`old_topic_model_<data-ora>/`);
- `topic2hier.json` (`topic2hier_<data-ora>.json`);
- un log degli spostamenti dei progetti già presenti (`reassign_<data-ora>.json`), con i topic precedenti e le versioni delle tabelle.

Da aggiungere a questo elenco: `assets/dmp_for_dash.html` e `data/project_graphs/`.

Tutto il resto (le tabelle `.lance`, `organisations.json`, `specter2.parquet`, `assets/treemap.json`) va copiato a mano.

---

## `update_db.py` in breve

```bash
python update_db.py                       # tutti gli step; con candidati a topic nuovi scrive anche il foglio di revisione
python update_db.py --review FILE         # applica il foglio di revisione compilato ai progetti già nel db, e termina
python update_db.py --projects            # solo alcuni step (anche combinati)
python update_db.py --no-review           # senza foglio di revisione
python update_db.py --config FILE         # usa un altro file di configurazione
```

Senza flag di step esegue tutti e quattro gli step, nell'ordine. I flag degli step si possono combinare (per esempio `--participants --deliverables`).

| Flag | Effetto |
|---|---|
| `--projects`, `--participants`, `--deliverables`, `--publications` | Eseguono solo gli step indicati |
| `--no-review` | Nessun foglio di revisione: ogni progetto tiene il topic esistente più vicino |
| `--review FILE` | Applica il foglio Excel di revisione compilato ai progetti **già nel db** e termina: non legge l'export e non si combina con i flag degli step né con `--no-review` |
| `--config FILE` | Usa un `settings.config` diverso da quello accanto allo script |

| Step | Cosa fa |
|---|---|
| **0** | Legge l'export, tiene solo i progetti **non ancora presenti** nel db e controlla che gli id siano numerici. |
| **1. Progetti** | Aggiunge i progetti nuovi a `projects_uncase` (con il loro embedding bge-m3) e assegna loro un topic con Specter2. I progetti poco simili a ogni topic esistente finiscono nella **revisione dei topic**. Aggiorna `specter2.parquet`, sposta eventuali progetti già presenti sui topic appena creati e rigenera la treemap. |
| **2. Partecipanti** | Per i progetti senza partecipanti aggiunge le righe a `participants` (una per paese se l'organizzazione ne ha più d'uno), aggiorna `organisations.json` con i nomi puliti e rigenera i grafi in `project_graphs/`. |
| **3. Deliverables** | Allinea `deliverables` all'export (titoli ufficiali, link correnti, deliverables spariti cancellati), conservando gli autori già estratti. Aggiorna `n_deliverables`. Solo con il formato a un file per progetto. |
| **4. Publications** | **Da completare.** Oggi il codice apre la tabella e non fa altro: i progetti nuovi hanno `n_publications = 0`. |
| **5. Indici** | Ricrea gli indici. Non esiste (e non deve esistere) un indice vettoriale su `projects_uncase.vector`. |

Cose da sapere:

- **Revisione dei topic.** Non richiede un terminale per chi la fa e **non blocca l'aggiornamento**. Il lancio normale esegue tutti gli step: i progetti poco simili ai topic esistenti entrano con un **topic provvisorio** (quello più vicino al loro cluster, `Unlabelled` se isolati) e viene scritto un foglio Excel con la data nel nome. Quando il revisore l'ha compilato, `update_db.py --review FILE` lo applica ai progetti già nel db; un errore nel foglio blocca tutto prima di scrivere. Un secondo lancio nello stesso giorno sovrascrive il foglio, in un giorno diverso ne scrive uno nuovo. Con `--no-review` non c'è foglio. Dettagli: [Review dei topic](review-topic.md).
- **Senza progetti nuovi si ferma tutto.** Lanciato senza flag, se l'export non ha progetti nuovi si interrompe prima di partecipanti e deliverables. Per rieseguire solo quegli step si usano i flag (`--participants`, `--deliverables`).
- **Ripresa dopo un errore.** Lo step 2 lavora sui progetti che non hanno ancora partecipanti, quindi se si interrompe dopo lo step 1 si può rilanciare con `--participants`. Lo step 3 scrive solo ciò che è cambiato: una seconda esecuzione sullo stesso export non scrive niente.
- **Le modifiche ai progetti già presenti non vengono applicate** (obiettivi corretti, contributi rivisti, partner aggiunti o tolti): la pipeline aggiunge solo progetti nuovi. Fa eccezione la tabella dei deliverables.

### Cosa si vede a terminale

Un run senza problemi stampa, in ordine, messaggi di questo tipo (alcuni compaiono solo se lo step è eseguito):

| Messaggio | Significato |
|---|---|
| `Reading new_data/<cartella> (records format)` | Formato dell'export riconosciuto (`records` o `legacy`) |
| `N new projects assigned to existing topics.` / `M have similarity < 0.92: ...` | Esito dell'assegnazione dei topic: quanti progetti hanno un topic esistente e quanti sono candidati a un topic nuovo |
| `Review sheet: K clusters, I isolated projects.` / `Fill in ...` | Foglio di revisione scritto (con la data nel nome); l'esecuzione prosegue, il foglio si applica poi con `--review` |
| `projects_uncase successfully updated!` | Fine dello step 1 sui progetti |
| `Specter2 embeddings stored (N projects in ...)` | `specter2.parquet` aggiornato; N è il totale dei progetti nell'archivio |
| `N projects of the sheet changed topic; M projects already in the db move to the new topics.` / `N projects moved to new topics (log: ...)` | Esito di `--review`: progetti del foglio che cambiano topic e progetti vecchi che passano ai topic nuovi; il log serve per il rollback |
| `participants successfully updated!` | Fine dello step 2 sui partecipanti |
| `project graph successfully updated!` | Grafi rigenerati |
| `deliverables: A added or updated, R old rows removed; K of T export deliverables have authors.` | Esito dello step 3 |
| `n_deliverables updated for N projects.` | Conteggi aggiornati (compare solo se cambiati) |
| `treemap successfully updated (...)!` | Treemap di Concept rigenerata |

**Messaggi che indicano che l'esecuzione si è fermata** (il processo termina senza completare lo step):

| Messaggio | Causa |
|---|---|
| `File di configurazione non trovato` / `You did not provide any new data directory` | `settings.config` mancante o senza `new_data_folder_name` |
| Errore sul formato dell'export | La cartella contiene entrambi i formati o nessuno dei due |
| `ATTENTION: project ids in new data are not int` | Nell'export c'è un `id` non numerico: va corretto prima di rilanciare |
| `There are no new projects. Aborting session.` | Nessun progetto nuovo rispetto al db |
| `Specter2 embeddings: ...` / `bge-m3 embeddings: ...` | Problema nei file di embedding (vedi P4) |
| `... contains N error(s): ...` | Con `--review`: il foglio compilato ha errori (con foglio e cella); il db non è stato toccato, si corregge il foglio e si rilancia |
| `Deliverables can only be updated from an export with one file per project` | Lo step 3 richiede il formato `records` (con il flag esplicito si ferma, altrimenti salta lo step e prosegue) |

Se lo script termina con un errore Python non elencato qui, il db può essere a metà di uno step: si ripristina dal backup fatto in P6.

---

## Passi successivi

### D1. Controllare i risultati

Verificare che i numeri tornino (progetti aggiunti, partecipanti, deliverables) e che il database sia nello stato atteso. Se qualcosa non va, ripristinare il backup.

Nella cartella `data_update/` c'è anche una suite di test (`pytest test.py -v`), che lavora su una copia ridotta dei dati e non scrive mai in `data/`.

### D2. Riavviare la dashboard

L'app legge elenco dei topic, contatori e grafi una volta sola e li tiene in memoria. Dopo l'aggiornamento, e dopo ogni `update_db.py --review`, va riavviata. Vedi [Pagina Query, sezione "Dopo un aggiornamento"](../02-dashboard/pagina-query.md#12-dopo-un-aggiornamento-del-database).

### D3. Aggiornare le parti statiche della dashboard

Non si aggiornano da sole:

- la nota sulla data dei dati nel testo introduttivo di Concept;
- la mappa dei progetti di Concept (`assets/dmp_for_dash.html`): **da completare**, non è ancora definito come si rigenera.

Vedi [Pagina Concept](../02-dashboard/pagina-concept.md#parti-statiche-da-tenere-allineate-a-mano).

### D4. Publications

**Da completare.** Va definito come si aggiornano le pubblicazioni (tabella `publications`, conteggio `n_publications`).

---

## ATTENZIONE: rotazione programmi quadro

Quando un nuovo programma quadro sostituirà Horizon Europe, l'aggiornamento **non funzionerà senza modifiche al codice**. Il programma nuovo va riconosciuto e gli va dato un codice (oggi Horizon 2020 = `8`, Horizon Europe = `9`).

**Da modificare:**

| Dove | Cosa |
|---|---|
| `data_update/update_db.py` | Il dizionario `FP_DICT` (oggi `{'HORIZON': 9}`) traduce il nome del programma nell'export nel codice numerico. Un programma non presente nel dizionario non viene tradotto. |
| `pages/rag.py` | Le opzioni del filtro "Framework Programme" sono scritte a mano. |
| `scripts/_rag__projects_list.py` | Il nome del programma nella lista dei progetti è dedotto da `fp == 8`. |
| `scripts/_rag__aggregated_view.py` | Il dizionario `fp_dict` dei nomi per i contatori. |
| `pages/overview.py` | La nota sulla data dei dati. |

Altri punti da controllare: `scripts/_overview.py` mostra il codice grezzo del programma (non il nome), e `cordis_loader.py` ricava `fp` dalle associazioni `programme` dell'export, quindi va verificato come il programma nuovo vi compare.

**Decisione da prendere in futuro:** cosa fare dei dati del programma quadro più vecchio (Horizon 2020 nel momento in cui il nuovo programma sarà entrato). Le opzioni sono tre:

1. **rimuoverlo dal db**;
2. **oscurarlo**, cioè tenerlo nel db ma non mostrarlo;
3. **tenerlo comunque**.

È una scelta di chi gestirà la piattaforma, da fare al momento della rotazione.

---

## Pagine collegate

- [Review dei topic](review-topic.md)
- [Struttura dei dati](../01-panoramica/struttura-dati.md): tabelle, formati dell'export, deliverables e publications, grafi.
