# Struttura dei dati

> **Scopo:** pagina di riferimento su cosa c'è nella cartella `data/` e negli altri file generati dalla pipeline, come sono fatte le tabelle, che cosa contengono i grafi dei progetti, come sono fatti i due formati dell'export CORDIS e come vengono gestiti deliverables e publications. Da consultare quando si lavora sui dati o sul codice che li legge.

I numeri riportati (righe, dimensioni) sono quelli del db al 2026-10-29, dopo l'aggiornamento con l'export del 2026-10-15 (step delle publications compreso).

## Cosa c'è in `data/`

La cartella `data/` **non è in git** (è nel `.gitignore`) e senza di essa la dashboard non parte. La scrive la pipeline di aggiornamento e la legge la dashboard.

| Elemento | Contenuto | Letto da |
|---|---|---|
| `projects_uncase.lance` | Un record per progetto: testo, topic, partecipanti (nomi), conteggi, embedding bge-m3 | dashboard, pipeline |
| `participants.lance` | Un record per coppia progetto-organizzazione (e paese) | dashboard, pipeline |
| `deliverables.lance` | Deliverables per progetto | dashboard, pipeline |
| `publications.lance` | Pubblicazioni per progetto | dashboard, pipeline |
| `organisations.json` | Dizionario `{organisationID: nome}` con i nomi puliti delle organizzazioni (62.392 voci) | pipeline |
| `topic2hier.json` | Gerarchia dei topic (formato in [Review dei topic](../03-aggiornamento-dati/review-topic.md#28-formato-di-topic2hierjson)) | dashboard (indirettamente), pipeline |
| `project_graphs/` | Grafi di collaborazione, un file JSON per topic (vedi sotto) | dashboard |
| `bge-m3-onnx/` | Modello bge-m3 in formato ONNX, per trasformare in vettore il testo libero della ricerca (circa 2 GB) | dashboard |
| `old_topic_model/` | Modello BERTopic dei topic ([Review dei topic](../03-aggiornamento-dati/review-topic.md#21-il-modello-dei-topic)) | pipeline |
| `specter2.parquet` | Embedding Specter2 di ogni progetto ([Review dei topic](../03-aggiornamento-dati/review-topic.md#211-archivio-degli-embedding-specter2)) | pipeline |
| `umap_model.joblib` | Modello UMAP della mappa di Concept (circa 1,1 GB: contiene i dati di training), usato per proiettare i progetti nuovi ([Mappa dei progetti](#mappa-dei-progetti)) | pipeline |
| `umap_2d.parquet` | Coordinate 2D di ogni progetto della mappa (`projectID`, `vector_2d`, non ruotate) | pipeline |
| `backups/` | Copie automatiche di `project_graphs/`, `dmp_for_dash.html`, modello e gerarchia, e log degli spostamenti ([elenco](../03-aggiornamento-dati/eseguire-update-db.md#p6-fare-il-backup)) | pipeline |

Due file generati dalla pipeline stanno invece in `assets/` (e quindi in git): `treemap.json` (la treemap di Concept) e `dmp_for_dash.html` (la mappa di Concept: vedi [Pagina Concept](../02-dashboard/pagina-concept.md)).

Quali file vengono modificati da ogni passo dell'aggiornamento è in [Eseguire l'aggiornamento dei dati](../03-aggiornamento-dati/eseguire-update-db.md#cosa-viene-modificato).

## Tabelle LanceDB

Le quattro tabelle sono aperte da `utils.py` all'avvio della dashboard. Gli id dei progetti sono interi (`int32`; fa eccezione `publications`, che usa `int64`).

### `projects_uncase`

Un record per progetto (59.344).

| Colonna | Tipo | Contenuto |
|---|---|---|
| `projectID` | int32 | Id del progetto in CORDIS |
| `title`, `objective`, `acronym` | stringa | Testi del progetto |
| `fp` | int8 | Programma quadro: `8` Horizon 2020, `9` Horizon Europe |
| `topic_name` | stringa | Nome del topic (il primo livello non `Unlabelled`) |
| `topic_name_hierarchy` | lista di 4 stringhe | Dalla foglia alla macro-area, allineata a destra con `Unlabelled` |
| `participants` | lista di stringhe | Nomi delle organizzazioni partecipanti, senza duplicati |
| `n_deliverables`, `n_publications` | int16 | Conteggi mostrati dalla dashboard |
| `vector` | lista fissa di 1024 float | Embedding bge-m3 di titolo e obiettivo, usato dalla ricerca con testo libero |

Un progetto appena aggiunto ha `participants` vuoto fino allo step 2 di `update_db.py`.

### `participants`

Un record per ogni **progetto, organizzazione e paese** (325.173). 

| Colonna | Tipo | Contenuto |
|---|---|---|
| `projectID` | int32 | Il progetto |
| `organisationID` | int32 | Id dell'organizzazione in CORDIS |
| `name` | stringa | Nome pulito (da `organisations.json`) |
| `countryCode` | stringa | Paese |
| `activityType` | stringa | `HES`, `PRC`, `REC`, `OTH`, `PUB` |
| `role` | stringa | `participant`, `coordinator`, `associatedPartner`, `thirdParty`, `partner`, `internationalPartner` |
| `netEcContribution` | double | Contributo UE all'organizzazione per il progetto (arrotondato all'euro quando viene scritto) |
| `fp`, `topic_name`, `topic_name_hierarchy` | come sopra | **Copiati dal progetto** |

Poiché `fp` e i topic sono copiati dal progetto, quando un progetto cambia topic vanno riscritte **entrambe** le tabelle (lo fa `update_db.py`: nei suoi step e con `--review`, per i progetti che cambiano topic).

### `deliverables`

Un record per deliverable (224.838).

| Colonna | Tipo | Contenuto |
|---|---|---|
| `projectID` | int32 | Il progetto |
| `title` | stringa | Titolo del deliverable |
| `physUrl` | stringa | Link al documento (può mancare) |
| `authors` | stringa JSON | `{"Nome Cognome": "Affiliazione"}`; `"{}"` se sconosciuti; l'affiliazione `Unknown` significa sconosciuta |
| `id` | stringa | Id CORDIS del deliverable (es. `101069359_20_DELIVHORIZON`); `null` nelle righe scritte dalla vecchia pipeline. La dashboard non lo legge |

### `publications`

Un record per pubblicazione (524.501: 503.067 da Scopus e 21.434 dall'export CORDIS).

| Colonna | Tipo | Contenuto |
|---|---|---|
| `projectID` | int64 | Il progetto |
| `title` | stringa | Titolo |
| `authors` | stringa JSON | Come nei deliverables. Nelle righe dall'export l'affiliazione è sempre `Unknown` |
| `physUrl` | stringa | Link alla pubblicazione: Scopus per le righe vecchie, `https://doi.org/<doi>` per quelle dall'export (può mancare) |
| `id` | stringa | Id CORDIS della pubblicazione (es. `101069359_24824_PUBLIHORIZON`); `null` nelle righe da Scopus. La dashboard non lo legge |

Lo step 4 aggiunge righe, ma non modifica né cancella quelle esistenti (vedi "Deliverables e publications").

### Indici

| Tabella | Indici |
|---|---|
| `projects_uncase` | `projectID` (BTree), `topic_name_hierarchy` (LabelList) |
| `participants` | `projectID` (BTree), `countryCode`, `activityType`, `fp` (Bitmap) |
| `deliverables` | `projectID`, `id` (BTree) |
| `publications` | `projectID`, `id` (BTree) |

### Due regole che la dashboard richiede

`data_update/lance_maintenance.py` le impone sulle tabelle `projects_uncase` e `participants`. `update_db.py` lo esegue a ogni avvio; si può lanciare anche da solo (da `data_update/`, `python lance_maintenance.py --data ../data`), per esempio su un db aggiornato con una versione precedente della pipeline.

1. **Nessun indice vettoriale su `projects_uncase.vector`.** La dashboard scarta i risultati con distanza coseno oltre 0,45. Un indice IVF_PQ restituisce distanze approssimate molto più alte di quelle vere (circa 0,76 invece di 0,41) e la ricerca con testo libero tornerebbe vuota. Senza indice la ricerca è esatta e sui circa 59.000 progetti resta veloce.
2. **Nessuna colonna di tipo dictionary** (`topic_name`, `role`). Le righe aggiunte in seguito hanno un dizionario proprio e `to_pandas()` su risultati che mescolano righe vecchie e nuove fallisce con l'errore `Categorical categories must be unique`. Le colonne vengono riscritte come stringhe: per la dashboard non cambia nulla.

I test leggono le tabelle con un semplice `to_pandas()`, come la dashboard, quindi questi due problemi emergono come test falliti.

## Grafi dei progetti e treemap

### Grafi in `data/project_graphs/`

Il tab "Project graph" della pagina Query non calcola nulla durante la ricerca: legge file già pronti.

- C'è **un file JSON per topic**, più un `_index.json` che associa il nome del topic al nome del file (oggi 204 voci). Il nome del file è il nome del topic con i caratteri speciali sostituiti da `_`.
- Ogni file ha `topic_name`, `nodes` (`{projectID: {"title": ...}}`) e `edges` (`source`, `target`, `weight`, `collaborators`).
- **Un arco collega due progetti dello stesso topic che hanno almeno un'organizzazione in comune**; `weight` è il numero di organizzazioni condivise e `collaborators` la loro lista. Il confronto è fatto sui **nomi** nella colonna `participants`.
- Il grafo è per **nome di topic**: più id di topic con lo stesso nome (alias) condividono lo stesso file.
- Il codice è `data_update/create_projgraph.py`. `rebuild_project_graphs` (in `topic_review.py`) lo esegue su tutti i progetti: lo fanno lo step 2 di `update_db.py` e `--review`, quando cambiano i topic dei progetti. I file dei topic spariti non vengono cancellati.
- La dashboard legge i file alla prima richiesta e li tiene in memoria: dopo un aggiornamento serve riavviarla.

### Treemap

`assets/treemap.json` è la figura della treemap di Concept. La genera `data_update/generate_treemap.py` a partire da `topic2hier.json`: il valore di ogni nodo è il numero di progetti di `projects_uncase` che passano da quel nodo. `update_db.py` la rigenera alla fine dello step 1 e dopo ogni `--review`. Si può lanciare anche da sola (`python generate_treemap.py`). Dettagli in [Pagina Concept](../02-dashboard/pagina-concept.md#treemap).

### Mappa dei progetti

`assets/dmp_for_dash.html` è la mappa di Concept. La genera `data_update/generate_datamapplot_representation.py`; `update_db.py` la rigenera subito dopo la treemap.

- **`data/umap_model.joblib`** è il modello UMAP con cui fu fatta la mappa originale (vicini 15, distanza minima 0, metrica coseno, `random_state=1`). Pesa circa 1,1 GB perché contiene i dati di training, necessari a `transform`. Non cambia con gli aggiornamenti.
- **`data/umap_2d.parquet`** associa ogni `projectID` (int32) alle sue coordinate 2D (`vector_2d`), **non ruotate**: la rotazione si applica solo al momento del disegno. Il modello da solo non basta, perché le sue coordinate di training non hanno gli id.
- **Progetti nuovi.** Sono quelli presenti in `specter2.parquet` ma non in `umap_2d.parquet`: il codice li proietta con il modello e li aggiunge. I punti già presenti non si spostano. Dato che si basa sul confronto tra i due file, un aggiornamento interrotto o dei progetti rimasti senza coordinate vengono recuperati al lancio successivo. I punti nuovi sono posizionati rispetto ai dati di training originali: dopo molti aggiornamenti può convenire rifare il fit completo.
- **Disegno.** Titoli ed etichette (un livello per colonna di `topic_name_hierarchy`, foglia per prima) vengono da `projects_uncase`; si disegnano solo i progetti che hanno coordinate. Con circa 59.000 punti ci vogliono circa 25 secondi.
- **Se qualcosa manca** (modello, file delle coordinate, libreria `datamapplot`) o la generazione fallisce, la pipeline non si ferma: stampa `WARNING: datamapplot not updated (...)` e il file vecchio resta.
- **Prima creazione di `umap_2d.parquet`** (già fatta): `python generate_datamapplot_representation.py --bootstrap FILE`, dove FILE è un parquet con `projectID` (stringa) e `vector` (2D) nello stesso ordine dei dati di training del modello. Tiene solo gli id numerici presenti in `specter2.parquet`.

## Formati dell'export CORDIS

CORDIS ha cambiato il formato del suo export JSON a maggio 2026. La pipeline legge entrambi i formati con `data_update/cordis_loader.py`, che sceglie quello giusto guardando il contenuto della cartella (`detect_format`). Errore se la cartella contiene entrambi i formati o nessuno dei due: in ogni cartella va tenuto un solo export.

| | **legacy** | **records** |
|---|---|---|
| Struttura | file tabellari unici: `project.json`, `organization.json`, `webLink.json`, ... | un file per progetto, `project-rcn-<rcn>_en.json`, gerarchico come l'XML |
| Nomi delle colonne | da `[columns]` in `settings.config` | fissi nel codice |
| Titoli dei deliverables | non presenti | presenti |
| Aggiornamento deliverables (step 3) | solo con il file di `extract_deliverables.py` (altrimenti lo step viene saltato) | possibile |
| Pubblicazioni (step 4) | non presenti (lo step viene saltato) | presenti |

`load_projects`, `load_organizations`, `load_weblinks` restituiscono gli stessi DataFrame per entrambi i formati, con i nomi di colonna usati da `update_db.py`:

- progetti: `projectID, title, objective, fp, acronym`
- organizzazioni: `organisationID, name, countryCode, activityType, role, netEcContribution, projectID`
- link: `id, projectID, physUrl, type`
- deliverables (solo records): `id, projectID, title, physUrl`
- pubblicazioni (solo records): `id, projectID, title, authors, physUrl`

### Come si leggono i file `records`

| Campo | Da dove |
|---|---|
| `projectID` | `id` (stringa, convertita in intero) |
| `fp` | Dalle associazioni `programme` collegate (`frameworkProgramme`, prima la base giuridica). Il valore (es. `HORIZON`) viene poi tradotto in codice numerico da `FP_DICT` in `update_db.py` |
| Partecipanti | Associazioni `organization`: ruolo da `attributes.type`, nome da `legalName`, paese da `address.country`, contributo da `attributes.netEcContribution` (stringa, convertita in numero) |
| `activityType` | La categoria `organizationActivityType`, con la barra iniziale tolta (`/PRC` diventa `PRC`) |
| Deliverables | Associazioni `result` della collezione `/deliverable`; `id` come `101069359_20_DELIVHORIZON`; `title` ufficiale; `physUrl` dal `webLink` annidato di tipo `projectDeliverable` (assente in 827 deliverables su 63.000 nell'export del 2026-10-15) |
| Pubblicazioni | Associazioni `result` della collezione `/publication` (`/pubsum` e `/ipr` sono ignorate); `id` come `101069359_24824_PUBLIHORIZON`; autori dal testo libero `<authors>` dentro `details`; `physUrl` dal DOI |

Altre note:

- I progetti del formato `records` sono ordinati per `projectID`. 
- Un `id` non numerico lascia `projectID` come decimale e `update_db.py` si ferma con un messaggio.
- Nello stesso progetto o tra progetti, deliverables con lo stesso id fanno fermare il caricamento.
- L'export non contiene gli autori dei deliverables. Contiene anche una descrizione e un tipo del deliverable (`deliverableType`) che la pipeline deliberatamente non salva.
- Le modifiche ai progetti già presenti nel db (obiettivi corretti, contributi rivisti, partner aggiunti o tolti, deliverables ricaricati con un nuovo link) non vengono applicate, salvo per i deliverables (step 3).

## Deliverables e publications

### Deliverables (step 3 di `update_db.py`)

- **Due fonti possibili**, scelte con `deliverables_file` in `settings.config`:
  - **vuoto (default)**: i deliverables dell'export, con gli autori già presenti nel db. Nessun PDF viene letto, quindi i deliverables nuovi restano senza autori;
  - **il parquet scritto da `extract_deliverables.py`** (vedi [P3](../03-aggiornamento-dati/eseguire-update-db.md#p3-estrarre-gli-autori-dei-deliverables-facoltativo)): sostituisce sia l'export sia il riuso degli autori, che lo script ha già fatto; gli autori vengono scritti così come sono nel file.
- Per ogni progetto dell'export (anche senza deliverables), la tabella segue l'export: titolo ufficiale e link correnti; i deliverables spariti da CORDIS vengono cancellati; le righe senza `id` (scritte dalla vecchia pipeline) vengono sostituite.
- Gli **autori** si conservano: per `id`, altrimenti per `physUrl` dalle righe vecchie, altrimenti `"{}"`.
- Le righe dei progetti **non presenti nell'export** (tutta la parte Horizon 2020, `id` nullo) non vengono toccate. Oggi: 63.280 righe con `id`, 161.558 senza, 174.794 con autori.
- Le scritture vanno **prima** e le cancellazioni **dopo**, così un'interruzione non fa perdere autori. Una seconda esecuzione sullo stesso export non scrive niente.
- `n_deliverables` in `projects_uncase` deve essere uguale al numero di righe del progetto in `deliverables` (compresi i deliverables senza link). Gli step 1 e 3 lo tengono allineato; lo step 3 scrive solo i conteggi cambiati.
- Con un export `legacy` e `deliverables_file` vuoto lo step 3 viene saltato (con `--deliverables` esplicito il programma si ferma).
- **Autori estratti con l'LLM.** `extract_deliverables.py` legge le prime 3 pagine del PDF e chiede all'LLM gli autori di quel documento con l'affiliazione (`Unknown` se manca), escludendo revisori, contributori e autori citati. Al 2026-10-29 non è ancora stato lanciato sui dati reali.

### Publications (step 4)

- Le **503.067 righe già presenti** vengono da Scopus (con le affiliazioni degli autori) e **non vengono mai toccate**.
- Lo step 4 aggiunge le pubblicazioni **dell'export** solo per i progetti che sono nell'export e che nel db hanno `n_publications = 0`: i progetti nuovi dello stesso lancio, ma anche progetti vecchi rimasti senza pubblicazioni. I progetti con `n_publications > 0` restano come sono. Poi aggiorna `n_publications` dei progetti scritti.
- Le righe si scrivono con `merge_insert` sulla colonna `id`, aggiunta alla tabella alla prima esecuzione. Una seconda esecuzione sullo stesso export non scrive niente, perché i progetti trattati hanno ormai `n_publications > 0`.
- Un progetto con `n_publications = 0` ma con righe nella tabella viene saltato con un avviso, per non creare doppioni.
- **Autori**: l'export non ha le affiliazioni, quindi `authors` è `{"Nome": "Unknown"}` (la dashboard mostra solo il nome), `"{}"` se mancano (645 su 95.000). I nomi vengono dal campo di testo libero `<authors>`: separati da `;` se ce n'è uno, altrimenti da virgole, con `and`/`&` prima dell'ultimo. È un'euristica: un elenco come `Rossi, M., Bianchi, L.` viene spezzato in pezzi che non sono nomi interi.
- **Link**: `https://doi.org/<doi>`, assente senza DOI (10.000 su 95.000). Anno, rivista, editore e tipo sono nell'export ma non vengono salvati.
- Con un export `legacy` lo step viene saltato (con `--publications` esplicito il programma si ferma).
- **Primo lancio** (export del 2026-10-15): 21.434 pubblicazioni per 4.075 progetti; 14.060 progetti dell'export non ne hanno nessuna. Oggi i progetti con `n_publications = 0` sono 25.714.
- `publications_file` in `settings.config` è riservato a una futura fonte esterna (per esempio una nuova estrazione da Scopus, con le affiliazioni): l'import **non è implementato** e, se il parametro è compilato, lo step viene saltato.

## Cose da sapere sui dati

- **Dati denormalizzati.** `fp` e i topic sono nelle due tabelle; un cambio di topic va scritto in entrambe.
- **Download da browser.** Le cartelle `.lance` scaricate con un browser possono avere i file `_versions/*.manifest` rinominati in `*.manifest.appcache`: LanceDB poi segnala `Table ... was not found`. Basta togliere il suffisso.
- **Riavvio.** La dashboard tiene in memoria l'elenco dei topic, i contatori e i grafi: dopo ogni aggiornamento va riavviata.
