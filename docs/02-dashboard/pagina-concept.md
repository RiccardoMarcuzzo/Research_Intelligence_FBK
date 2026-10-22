# Pagina Concept

> **Scopo:** descrive la pagina Concept (`/concept`): cosa mostra all'utente, da dove prende i dati e quali parti sono statiche e vanno tenute allineate a mano. Da leggere per usarla o per modificarla.

La pagina si chiama **Concept** nella barra di navigazione e **Overview** nel titolo della scheda del browser (`pages/overview.py`). Il percorso è `<base>/concept`, ed è la pagina introduttiva: spiega da dove vengono i dati e come sono stati organizzati i topic.

Codice: `pages/overview.py` (layout e callback) e `scripts/_overview.py` (pannello dei dettagli del progetto).

## Cosa vede l'utente

Dall'alto in basso:

| Sezione | Contenuto |
|---|---|
| **Introduzione** | Breve testo su CORDIS e sulla piattaforma, con una nota sulla data di aggiornamento dei dati. |
| **Tre contatori** | Progetti, organizzazioni e topic presenti nel database. |
| **Mappa dei progetti** ("Explore the Project Latent Space") | Mappa 2D interattiva: ogni punto è un progetto, i colori indicano i cluster di topic. Al passaggio del mouse mostra gli attributi del progetto. Al clic si apre un pannello laterale con i dettagli. |
| **Treemap della tassonomia** ("Explore the Topic Taxonomy") | Rettangoli annidati: i topic di primo livello si aprono nei sotto-topic, con la quota percentuale e il numero di progetti. Un clic entra in un topic, la barra in alto riporta al livello superiore. |
| **Collegamento alla pagina Query** | Scheda con pulsante verso `/query`. |
| **"Meet the Team"** | Persone del gruppo, ruolo e indirizzo e-mail di contatto. |

Il testo accanto alla mappa e alla treemap spiega la metodologia: embedding Specter2, riduzione con UMAP, clustering HDBSCAN, tassonomia BERTopic con clustering agglomerativo, revisione manuale (human-in-the-loop) ed etichette generate da un LLM. Il dettaglio tecnico sta in [Review dei topic](../03-aggiornamento-dati/review-topic.md#21-il-modello-dei-topic).

### Pannello dei dettagli di un progetto

Cliccando un punto della mappa si apre un pannello a destra con:

- titolo e link "View on Cordis";
- programma quadro;
- topic (percorso gerarchico, senza i livelli `Unlabelled`);
- partecipanti;
- abstract (l'obiettivo del progetto).

## Come è costruita

### Contatori

Si calcolano **una volta all'avvio** in `utils.py` (`PROJs_No`, `ORGs_No`, `TOPs_No`) e un callback li scrive nelle tre schede.

- Progetti: `projectID` distinti in `projects_uncase`.
- Organizzazioni: `organisationID` distinti in `participants`.
- Topic: valori distinti di `topic_name_hierarchy`, esclusi gli `Unlabelled`.

Dopo un aggiornamento del database **serve un riavvio** dell'app perché i numeri cambino. Non filtrano per programma quadro: contano tutto ciò che è nel database.

### Treemap

- Il file è `assets/treemap.json`. Il callback `load_treemap` lo legge a ogni caricamento della pagina e lo mostra come figura Plotly.
- Lo **genera la pipeline** (`data_update/generate_treemap.py`): la struttura dell'albero viene da `data/topic2hier.json`, e il valore di ogni nodo è il numero di progetti di `projects_uncase` che passano da quel nodo.
- `update_db.py` lo rigenera alla fine del passo dei progetti; lo rigenera anche `reassign_existing.py`. Si può lanciare anche da solo (`python generate_treemap.py`). Vedi [Struttura dei dati](../01-panoramica/struttura-dati.md#grafi-dei-progetti-e-treemap).
- I colori dei cinque rami principali sono fissi nel codice (`ROOT_COLORS`); un ramo nuovo avrebbe un grigio di default.
- I progetti `Unlabelled` non compaiono.

Poiché è un file letto a ogni richiesta, **dopo un aggiornamento la treemap cambia senza riavviare**.

### Mappa dei progetti

- È un file HTML già pronto, `assets/dmp_for_dash.html` (circa 4 MB), mostrato in un `iframe`, prodotto con la libreria *datamapplot*.
- Quando l'utente clicca un punto, la pagina HTML invia un messaggio al genitore (`postMessage` con tipo `point-clicked` e l'`id` del progetto). Un callback clientside lo salva in `message-store`, il pannello laterale si apre e `scripts/_overview.py` legge il progetto da `projects_uncase` (`populate_doc_canvas`).

## Parti statiche da tenere allineate a mano

Queste cose **non si aggiornano da sole** con la pipeline:

| Cosa | Dove | Problema |
|---|---|---|
| Nota "Data regarding Horizon Europe projects are current through the end of 2024." | `pages/overview.py`, testo introduttivo | La data è scritta nel testo. Va aggiornata a ogni export. |
| Mappa dei progetti | `assets/dmp_for_dash.html` | I progetti nuovi non compaiono finché il file non viene rigenerato. |
| Testo sulla metodologia (50 combinazioni di iperparametri, soglia 0,99 per il rumore) | `pages/overview.py` | Descrive il lavoro fatto in origine; non cambia con gli aggiornamenti, ma va riletto se il metodo cambia. |
| Sezione "Meet the Team" | `pages/overview.py` | Nomi, ruoli ed e-mail sono scritti nel codice, e le immagini stanno in `assets/img/`. Vanno aggiornati quando cambia chi segue il progetto. |

## Punti fragili

- **Dipendenza dal web.** La pagina HTML della mappa carica il font da Google Fonts: senza connessione a internet il font non viene caricato (la mappa funziona comunque).

## Pagine collegate

- [Architettura](../01-panoramica/architettura.md#pagina-concept-concept): flusso tecnico della pagina.
- [Struttura dei dati](../01-panoramica/struttura-dati.md#grafi-dei-progetti-e-treemap)
- [Review dei topic](../03-aggiornamento-dati/review-topic.md)
