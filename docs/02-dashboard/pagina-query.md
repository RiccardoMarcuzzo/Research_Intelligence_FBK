# Pagina Query

> **Scopo:** descrive tutto ciò che avviene nella pagina Query (`/query`): filtri, ricerca con testo libero, i tre tab dei risultati, il download CSV, il pulsante "Why is this relevant?", i parametri di configurazione e come modificare il codice. È la pagina principale della dashboard: chi deve usarla o cambiarla trova qui tutto.

La pagina compare nella barra di navigazione come **Query**; nel titolo della scheda del browser si chiama **RAG** (`PAGE_TITLE` in `pages/rag.py`). Il percorso è `<base>/query`, dove `<base>` è il valore di `--path` (default `/research_intelligence/`).

**Codice:**

| File | Contenuto |
|---|---|
| `pages/rag.py` | Layout della pagina e tutti i callback. |
| `scripts/_rag.py` | Costruzione dei filtri, embedding del testo, ricerca vettoriale. |
| `scripts/_rag__projects_list.py` | Tab "Projects list". |
| `scripts/_rag__aggregated_view.py` | Tab "Aggregated view". |
| `scripts/_rag__projects_graph.py` | Tab "Project graph". |
| `scripts/_explainability_api.py` | Pulsante "Why is this relevant?". |
| `app.py` | Un callback clientside che apre CORDIS al clic su un nodo del grafo. |

---

## 1. Cosa vede e cosa può fare l'utente

La pagina ha tre zone, dall'alto in basso.

**Filtri** (prima riga), tutti a selezione multipla:

| Etichetta | Opzioni |
|---|---|
| Framework Programme | Horizon 2020, Horizon Europe |
| Country | Tutti i paesi di `COUNTRY_CODES` in `utils.py`, in ordine alfabetico |
| Organisation type | REC, HES, PRC, PUB, OTH |
| Organisation | Si riempie mentre si digita (vedi sotto) |
| Topic | Tutti i topic del database |

**Testo libero e pulsanti** (seconda riga): una casella di testo ("Type your description here...") e i pulsanti **Retrieve**, **Reset** e **Download**. Sotto, l'interruttore **Show coordinator only**.

**Risultati**: compaiono dopo il primo clic su Retrieve, in tre tab: *Projects list*, *Aggregated view*, *Project graph*.

Sopra i risultati c'è un link "documentation" che porta alla pagina Concept (`/concept`).

---

## 2. Filtri e testo libero

### 2.1 Regole di combinazione

- **Dentro un filtro** vale "oppure": scegliendo Italia e Francia, si accettano entrambe.
- **Tra filtri diversi** vale "e".
- **Retrieve con tutto vuoto non fa nulla**: serve almeno un filtro o un testo. L'interruttore "coordinator only" da solo non basta.
- I filtri si applicano alle **righe dei partecipanti** (tabella `participants`, una riga per coppia progetto-organizzazione). Vuol dire che i filtri sui partecipanti valgono **insieme sulla stessa riga**: *Country = Italia* e *Organisation type = HES* cercano un partecipante che sia italiano **e** università, non un progetto che ha un partecipante italiano e, da un'altra parte, un'università.
- Un progetto entra nei risultati se **almeno una** sua riga soddisfa tutti i filtri.

### 2.2 Filtri

| Filtro | Cosa fa | Colonna usata |
|---|---|---|
| Framework Programme | Tiene i progetti dei programmi scelti. I valori sono scritti a mano nel layout: Horizon 2020 = `8`, Horizon Europe = `9`. | `fp` |
| Country | Tiene i partecipanti dei paesi scelti. | `countryCode` |
| Organisation type | Tiene i partecipanti del tipo scelto: REC (centri di ricerca), HES (università), PRC (aziende private), PUB (enti pubblici), OTH (altro). | `activityType` |
| Organisation | Tiene i partecipanti con quel nome esatto. | `name` |
| Topic | Tiene i progetti che hanno quel topic **a qualsiasi livello della gerarchia**. Scegliere un topic di livello alto (per esempio una macro-area) include tutti i topic sotto di esso. Il valore `Unlabelled` non è tra le opzioni. | `topic_name_hierarchy` (lista) |
| Show coordinator only | Tiene solo le righe in cui il ruolo è `coordinator`. | `role` |

L'interruttore **cambia i risultati subito**, senza bisogno di ripremere Retrieve (il callback ascolta anche lui). Combinato con altri filtri, vuol dire "progetti in cui un'organizzazione che soddisfa i filtri è coordinatrice".

Valori di `role` presenti nel db: `participant`, `coordinator`, `associatedPartner`, `thirdParty`, `partner`, `internationalPartner`.

#### 2.2.2 Il filtro Organisation

- All'apertura non ha opzioni. L'elenco si costruisce **mentre l'utente digita**: ogni volta che cambia il testo di ricerca, il callback `update_dropdown_org_filter` interroga la tabella `participants`.
- La ricerca cerca il testo come sottostringa, senza distinzione tra maiuscole e minuscole, sul nome. Rispetta i filtri *Country* e *Organisation type* già impostati.
- Legge al massimo 200 righe e mostra al massimo **20 nomi distinti**. Per trovare un'organizzazione con nome comune può servire scrivere più caratteri.
- Le organizzazioni già selezionate restano nell'elenco.

### 2.3 Testo libero (ricerca semantica)

Nella casella si può scrivere:

- il titolo, l'acronimo o parte dell'obiettivo di un progetto (per esempio "ODEUROPA");
- un tema che non è tra i topic (per esempio "disinformation in public speech");
- l'intera descrizione di una proposta di progetto.

### 2.4 Risultati

**Se c'è ricerca testuale:**

1. Il testo viene portato in minuscolo, gli spazi multipli vengono ridotti a uno e il risultato è trasformato in un vettore con il modello **bge-m3** (formato ONNX in `data/bge-m3-onnx`, eseguito su CPU; massimo 8192 token, il resto viene troncato).
2. Il vettore viene confrontato con i vettori dei progetti (`projects_uncase.vector`, 1024 dimensioni) con la **distanza coseno**. La ricerca è esatta: non deve esserci un indice vettoriale sulla colonna (vedi [Struttura dei dati](../01-panoramica/struttura-dati.md#due-regole-che-la-dashboard-richiede)).
3. Se ci sono anche filtri, la ricerca avviene **solo sui progetti che li soddisfano**.
4. Si tengono al massimo **200 progetti** (`RETRIEVAL_THRESHOLD` in `utils.py`) e si scartano quelli con distanza oltre **0,45** (cioè similarità inferiore a 0,55).
5. Se i risultati "forti" (cioè quelli la cui distanza dal testo non supera quella del miglior risultato di più del 10%) sono **meno di 50**, scatta un **allargamento**: si calcola il centroide dei risultati forti, si cerca di nuovo intorno al centroide e si uniscono i nuovi progetti ai precedenti (senza duplicati, sempre al massimo 200).
6. I progetti sono ordinati dal più simile al meno simile.

Se la ricerca non trova nulla sotto la soglia, il risultato è vuoto ("No projects found").

**Se non ricerca testuale:** 

- non c'è limite al numero di progetti e l'ordine non ha un significato (è quello in cui compaiono nella tabella dei partecipanti).

### 2.5 Reset

Il pulsante **Reset** svuota i cinque filtri e il testo, e azzera i risultati. Non reimposta l'interruttore "coordinator only".

## 2.6 Download CSV

Il pulsante **Download** scarica un CSV dello **store dei partecipanti**, quindi con le stesse regole della vista aggregata: righe dei partecipanti che hanno superato i filtri (coordinator incluso), dei progetti trovati.

- **Nome del file:** `AAAA-MM-GG_HH-MM-SS.csv`.
- **Righe iniziali** che cominciano con `#`: data di esportazione, come leggerlo in pandas (`pd.read_csv('<file>.csv', comment='#')`), la descrizione delle colonne e il numero di righe.
- **Colonne:**

| Colonna | Significato |
|---|---|
| `projectID` | Identificativo CORDIS del progetto |
| `organisationID` | Identificativo CORDIS dell'organizzazione |
| `countryCode` | Paese dell'organizzazione |
| `activityType` | Tipo di organizzazione (REC, HES, PRC, PUB, OTH) |
| `role` | Ruolo nel progetto |
| `netEcContribution` | Contributo UE all'organizzazione per il progetto |
| `fp` | Programma quadro (`8` o `9`) |
| `name` | Nome dell'organizzazione |
| `topic_name_hierarchy` | Gerarchia del topic del progetto |

- Il file **non contiene titolo né obiettivo** dei progetti, solo i loro identificativi.
- `topic_name` viene escluso dal file. L'ordine delle colonne nel file non coincide con quello della descrizione.
- Se non c'è stata nessuna ricerca (o dopo Reset) il pulsante non fa nulla.

---

## 3. Cosa succede quando si preme Retrieve

1. `show_tabs` rende visibile il blocco dei tab.
2. `retrieve_idx` (in `pages/rag.py`) legge filtri e testo e chiama `retrieve_results_df` (in `scripts/_rag.py`), che:
   1. costruisce una clausola SQL `where` sulla tabella `participants` a partire dai filtri (valori testuali con gli apici raddoppiati per evitare errori di sintassi);
   2. legge le righe dei partecipanti che la soddisfano e ne ricava i `projectID` distinti;
   3. se c'è un testo, applica la ricerca semantica descritta sopra e restringe le righe ai progetti trovati.
3. Il risultato finisce in due `dcc.Store` nel browser:
   - **`retrieved-projects-store`**: lista ordinata di `projectID`;
   - **`retrieved-participants-store`**: le righe di `participants` dei progetti trovati, come JSON (`orient='split'`). Sono **solo le righe che soddisfano i filtri**, non tutti i partecipanti dei progetti.
4. Ogni tab ha un callback che si attiva al cambio di uno store e costruisce il proprio contenuto.

Conseguenza da ricordare: **la lista dei progetti mostra tutti i partecipanti di ogni progetto** (li legge da `projects_uncase.participants`), mentre **la vista aggregata e il CSV contengono solo i partecipanti che hanno superato i filtri**. Con *Country = Italia*, la vista aggregata parla solo delle organizzazioni italiane.

| Callback | Si attiva con | Aggiorna |
|---|---|---|
| `update_dropdown_org_filter` | testo digitato nel filtro Organisation | opzioni del filtro Organisation |
| `show_tabs` | Retrieve | visibilità dei tab |
| `retrieve_idx` | Retrieve, interruttore coordinator | i due store |
| `reset_filters` | Reset | filtri, testo, store, testo iniziale |
| `display_projects` | store dei progetti, Prev, Next | tab Projects list |
| `toggle_section` | clic su Deliverables/Publications | tabella aperta |
| `show_why_relevant` | clic su "Why is this relevant?" | spiegazione |
| `display_aggregated` | store dei partecipanti | tab Aggregated view |
| `update_agg_graph`, `update_agg_orgs_graph` | scelta della metrica, slider, store | grafici |
| `display_project_graph` | store dei progetti | tab Project graph |
| `update_project_graph` | clic sul grafo, Back, slider | figura del grafo |
| `download_csv` | Download | file CSV |

---

## 4. Tab "Projects list"

Mostra i progetti trovati come elenco a fisarmonica, **15 per pagina** (`PAGE_SIZE` in `pages/rag.py`), con pulsanti *Prev* e *Next* e la scritta "Showing X–Y of N projects". Le pagine si cambiano senza rifare la ricerca. Il costruttore è `build_accordion_items` in `scripts/_rag__projects_list.py`.

### Intestazione di ogni progetto

`ACRONIMO - Titolo`, poi: programma quadro (nome, non codice), percorso del topic (senza i livelli `Unlabelled`, separati da →) e il link **View on CORDIS ↗** (`https://cordis.europa.eu/project/id/<projectID>`).

### Corpo (aprendo il progetto)

- **Why is this relevant?** (solo se la ricerca ha un testo): vedi la sezione 8.
- **Participants**: elenco dei nomi delle organizzazioni.
- **Objective**: il testo dell'obiettivo.
- **Deliverables (n)** e **Publications (n)**: sezioni richiudibili, presenti solo se il progetto ne ha (`n_deliverables` / `n_publications` maggiore di zero). Il contenuto si carica da LanceDB **solo alla prima apertura**:
  - Deliverables: titolo, autori e link "Download deliverable↗" (se manca il link: "Not Available");
  - Publications: titolo, autori e link "See publication↗".
  - Gli autori sono salvati come testo JSON `{nome: affiliazione}`. Con affiliazione `Unknown` si mostra solo il nome; senza autori compare "—".

I conteggi `n_deliverables` e `n_publications` vengono dalla tabella `projects_uncase`, non dal numero di righe effettive: se i due non coincidono, il conteggio mostrato può non corrispondere alla tabella.

### "Why is this relevant?"

Compare nel corpo di ogni progetto **solo se la ricerca ha un testo libero**. Al clic:

1. la pagina invia titolo e obiettivo del progetto e il testo dell'utente a un servizio LLM esterno (POST con timeout di 120 secondi);
2. il servizio risponde con una spiegazione, mostrata in Markdown sotto il pulsante;
3. se la chiamata fallisce, la pagina mostra "Could not load explanation" con il motivo.

L'indirizzo del servizio è scritto nel codice (`scripts/_explainability_api.py`): `http://research-llm-api-matita:8060/v1/project/relevance`. Il servizio non è in questa repo. Se il server cambia, l'indirizzo va aggiornato nel codice. Vedi [Avvio della dashboard](avvio-dashboard.md#file-env).

---

## 5. Tab "Aggregated view"

Riassume il panorama trovato. Si costruisce a partire dallo store dei **partecipanti** (non dei progetti), dopo averlo raggruppato per organizzazione, ruolo, topic e programma quadro. Codice: `scripts/_rag__aggregated_view.py`.

### Riga dei contatori

| Contatore | Significato |
|---|---|
| FPs | Il nome del programma se ce n'è uno solo, altrimenti quanti sono |
| Projects | Progetti distinti |
| Countries, Org. Types, Organisations, Topics | Quanti valori distinti. Se c'è un solo valore viene mostrato il valore stesso. Se sono più di uno, la scheda è cliccabile e porta al grafico corrispondente. |
| EU Contribution | Somma di `netEcContribution`, scritta come `€ 1.2M`, `€ 340K` o `€ 800` |

### Scelta della metrica

Un selettore con: **Projects involved** (default), **Funding amount**, e **Organisations involved** (compare solo se le organizzazioni sono più di una).

### Grafici

Tutti seguono la metrica scelta. Un grafico compare **solo se ha più di un valore da confrontare**.

| Grafico | Tipo | Note |
|---|---|---|
| Per paese | barre orizzontali | |
| Per tipo di organizzazione | ciambella | |
| Top organizzazioni | barre orizzontali | Non compare con la metrica "Organisations involved". Uno slider (5–30, passo 5, default 10) sceglie quante mostrare. Il titolo dice "Top N Coordinators" se l'interruttore coordinator è attivo, altrimenti "Top N Participants". |
| Per topic | barre orizzontali | Usa il topic foglia (`topic_name`), non la gerarchia |

Passando il mouse su una barra si vedono progetti, euro finanziati e numero di organizzazioni.

---

## 6. Tab "Project graph"

Mostra come si collegano tra loro i progetti trovati e quelli simili. Codice: `scripts/_rag__projects_graph.py`.

### Cosa rappresenta

- Ogni punto è un progetto. **Arancione** (`#FF8C00`): progetti trovati dalla ricerca. **Grigio**: i loro "vicini" nello stesso topic.
- Due progetti sono collegati se hanno **lo stesso topic** e condividono **almeno N organizzazioni partecipanti**. Lo slider *Min. shared collaborators* imposta N (da 1 a un massimo di 10 o meno, a seconda dei dati; valore iniziale 2).
- Si disegnano solo i progetti trovati e i vicini che hanno almeno un collegamento di peso almeno N.
- I grafi **non si calcolano durante la ricerca**: sono file già pronti in `data/project_graphs/` (un JSON per topic, più `_index.json`), generati dalla pipeline con `create_projgraph.py`. La pagina prende da lì, per ogni progetto trovato, i suoi collegamenti. Vedi [Struttura dei dati](../01-panoramica/struttura-dati.md#grafi-dei-progetti-e-treemap).

### Due viste

1. **Panoramica**: una griglia (5 colonne) di riquadri, uno per topic che contiene almeno un risultato. Passando il mouse su un riquadro compare il nome del topic, con "Click to expand".
2. **Dettaglio di un topic**: cliccando un riquadro si vede il grafo di quel topic, con i nodi disposti da un algoritmo a forze. Il pulsante **← Back** ritorna alla panoramica.
   - Passando il mouse su una linea: le organizzazioni condivise tra i due progetti ("Collaboratori condivisi").
   - Cliccando un punto: si apre la scheda CORDIS del progetto in una nuova scheda (callback clientside in `app.py`).

### Colori con il testo libero

Se la ricerca ha un testo, i punti non sono arancioni/grigi ma colorati con una scala di "Similarity" da 0 a 1. **Non è la similarità reale**: il valore è assegnato in base alla **posizione** del progetto nei risultati, con una scala lineare da 1,0 (primo) a 0,2 (ultimo). I vicini valgono 0.

### Limiti

- Con **500 progetti o più** il grafo non viene generato ("Too many projects. Skipping project graph generation.").
- Se un topic non ha il file del grafo, il suo grafo è vuoto.

---

## 7. Dati letti dalla pagina

| Tabella (in `data/`) | Colonne usate | Dove |
|---|---|---|
| `participants` | tutte: `projectID`, `organisationID`, `countryCode`, `activityType`, `role`, `netEcContribution`, `topic_name`, `fp`, `name`, `topic_name_hierarchy` | filtri, vista aggregata, CSV |
| `projects_uncase` | `projectID`, `title`, `fp`, `objective`, `topic_name`, `topic_name_hierarchy`, `participants`, `acronym`, `n_deliverables`, `n_publications`, `vector` | lista progetti, ricerca semantica, grafo |
| `deliverables` | `projectID`, `title`, `authors`, `physUrl` | sezione Deliverables |
| `publications` | `projectID`, `title`, `authors`, `physUrl` | sezione Publications |
| `project_graphs/` | grafi per topic | tab Project graph |

Il database contiene (stato al 2026-10-22): circa 59.300 progetti e 325.000 righe di partecipanti.

---

## 8. Parametri

| Parametro | Valore | Dove | Effetto |
|---|---|---|---|
| `RETRIEVAL_THRESHOLD` | 200 | `utils.py` | Massimo di progetti della ricerca con testo |
| `base_threshold` | 0,55 | `retrieve_results_df` | Similarità minima (distanza massima 0,45) |
| `min_results` | 50 | `retrieve_results_df` | Sotto questo numero di risultati forti scatta l'allargamento |
| Fattore "forti" | 1,10 | `retrieve_results_df` | Un risultato è forte se la sua distanza è al massimo 1,10 volte quella del migliore |
| `expansion_threshold` | 0,60 | `retrieve_results_df` | Presente tra i parametri ma **non usato** |
| `max_length` | 8192 | `encode` | Token massimi del testo |
| `PAGE_SIZE` | 15 | `pages/rag.py` | Progetti per pagina |
| Limite del grafo | 500 | `build_project_graph` | Oltre questa soglia il grafo non si genera |
| N iniziale del grafo | 2 | `build_project_graph` | Valore iniziale dello slider |
| Opzioni del filtro Organisation | 20 (da 200 righe) | `update_dropdown` | Nomi mostrati mentre si digita |
| Slider organizzazioni | 5–30, passo 5, default 10 | `build_aggregated_graphs` | Quante organizzazioni mostrare |
| Timeout del servizio LLM | 120 s | `call_relevance_api` | Attesa massima |

---

## 11. Come modificare la pagina

### Aggiungere un filtro

1. In `pages/rag.py`, aggiungere un `dcc.Dropdown` con un nuovo `id` nella prima riga del layout.
2. Aggiungerlo come `State` in `retrieve_idx` e passare il valore a `retrieve_results_df`.
3. In `retrieve_idx`, includerlo nella condizione `any([...])`.
4. In `scripts/_rag.py`, aggiungere il parametro a `retrieve_results_df` e una nuova condizione alla lista `conditions`, usando `_sql_scalar_in_clause` (colonna con un solo valore) o `_sql_array_overlap_clause` (colonna lista). La colonna deve esistere in `participants`.
5. In `reset_filters`, aggiungere un `Output` e il valore di ripristino.

### Cambiare le opzioni di Framework Programme

Le due voci sono nel layout (`options` di `fp-filter-proj`). In `scripts/_rag__projects_list.py` (`'Horizon 2020' if row['fp'] == 8 else 'Horizon Europe'`) e in `scripts/_rag__aggregated_view.py` (`fp_dict`) il nome è dedotto in modo fisso dai codici 8 e 9. Con un nuovo programma quadro vanno aggiornati **tutti e tre** i punti.

### Cambiare le soglie della ricerca

Vedi la tabella dei parametri. Per `RETRIEVAL_THRESHOLD` va modificato `utils.py`. Le altre sono argomenti di `retrieve_results_df`.

### Aggiungere un grafico alla vista aggregata

In `build_aggregated_graphs` (`scripts/_rag__aggregated_view.py`) si aggiunge un caso a `charts`, usando `build_graph` con la colonna da raggruppare. Se la colonna nuova non è tra `TITLE_MAP`, aggiungerla.

### Aggiungere un tab

Aggiungere un `dbc.Tab` in `results-tabs` (`pages/rag.py`) con un contenitore, scrivere uno `scripts/_rag__<nome>.py` con la funzione di costruzione e un callback che ascolta uno dei due store.

---

## 12. Dopo un aggiornamento del database

La dashboard legge alcuni dati **una sola volta all'avvio o alla prima richiesta e li tiene in memoria**:

| Cosa | Quando si carica | Dopo un update |
|---|---|---|
| Elenco dei topic del filtro | all'avvio (`utils.py`) | serve riavviare l'app |
| Contatori della pagina Concept | all'avvio | serve riavviare l'app |
| Grafi dei progetti e il loro indice | alla prima richiesta, poi in cache | serve riavviare l'app |
| Modello bge-m3 | alla prima ricerca con testo | invariato |

Per questo, **dopo ogni aggiornamento dei dati è necessario riavviare l'app**. Se non si riavvia, i filtri e i grafi possono mostrare lo stato precedente.

---

## Pagine collegate

- [Pagina Concept](pagina-concept.md)
- [Avvio della dashboard](avvio-dashboard.md)
- [Architettura](../01-panoramica/architettura.md): flusso generale di una ricerca.
- [Struttura dei dati](../01-panoramica/struttura-dati.md): schemi delle tabelle, vincoli (niente indice vettoriale) e grafi dei progetti.
