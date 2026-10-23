# Documentazione – Research Intelligence (CORDIS)

Documentazione completa della piattaforma: cosa fa, come si usa, come si installa e come si aggiorna il database.
Il `README.md` nella radice della repo descrive in breve le funzionalità; qui c'è il dettaglio.

## Se vuoi... leggi...

| Obiettivo | Pagina |
|---|---|
| Capire cos'è la piattaforma | [Cosa fa la piattaforma](01-panoramica/cosa-fa-la-piattaforma.md) |
| Capire come è organizzato il codice | [Architettura](01-panoramica/architettura.md) |
| Usare la piattaforma | [02 Dashboard](02-dashboard/pagina-query.md) |
| Installare e avviare l'app | [Avvio della dashboard](02-dashboard/avvio-dashboard.md) |
| **Aggiornare il database con un nuovo export CORDIS** | [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md) |
| Capire come sono fatti i dati | [Struttura dei dati](01-panoramica/struttura-dati.md) |

## Indice

### 01 – Panoramica
- [Cosa fa la piattaforma](01-panoramica/cosa-fa-la-piattaforma.md)
- [Architettura](01-panoramica/architettura.md)
- [Struttura dei dati](01-panoramica/struttura-dati.md)

### 02 – Dashboard
- [Avvio della dashboard](02-dashboard/avvio-dashboard.md)
- [Pagina Query](02-dashboard/pagina-query.md)
- [Pagina Concept](02-dashboard/pagina-concept.md)

### 03 – Aggiornamento dei dati
- [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md)
- [Review dei topic](03-aggiornamento-dati/review-topic.md)

> Le sezioni sono numerate per l'ordine di lettura: se ne servono altre si aggiungono in coda senza rinominare nulla.

## Da completare

Parti della documentazione o del progetto che non sono ancora definite. Quando una voce viene risolta, va tolta da qui e dalla pagina in cui compare.

### Documentazione da scrivere

| # | Cosa manca | Dove compare |
|---|---|---|
| 1 | **Deploy sul nuovo server**: dove gira l'app, come si avvia (servizio, container...), reverse proxy, valore di `--path` | [Avvio della dashboard](02-dashboard/avvio-dashboard.md#deploy) |
| 2 | **Criteri di decisione della review dei topic**: quando accettare, rimappare o lasciare `Unlabelled`, e con quali segnali | [Review dei topic](03-aggiornamento-dati/review-topic.md#14-un-cluster) |
| 3 | **Verifiche e ripristino**: quali conteggi confrontare prima e dopo un aggiornamento e come tornare indietro da un backup (modello e gerarchia dalle copie, tabelle dalla versione indicata nel log) | [Review dei topic](03-aggiornamento-dati/review-topic.md#112-cosa-viene-scritto-e-dove-restano-i-backup), [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md#d1-controllare-i-risultati) |
| 4 | **Backup automatico** di `assets/dmp_for_dash.html` e `data/project_graphs/`, da aggiungere all'elenco dei backup | [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md#p6-fare-il-backup) |

### Funzioni da definire o completare

| # | Cosa manca | Dove compare |
|---|---|---|
| 5 | **Estrazione dei deliverables** (`extract_deliverables`): nella repo c'è solo la vecchia versione, e lo step 3 di `update_db.py` non ne legge il risultato; i deliverables nuovi restano senza autori | [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md#p3-estrarre-i-deliverables-da-completare), [Struttura dei dati](01-panoramica/struttura-dati.md#deliverables-step-3-di-update_dbpy) |
| 6 | **Aggiornamento delle publications**: lo step 4 di `update_db.py` non fa nulla e i progetti nuovi hanno `n_publications = 0` | [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md#d5-publications), [Struttura dei dati](01-panoramica/struttura-dati.md#publications-step-4) |
| 7 | **Mappa di Concept** (`assets/dmp_for_dash.html`): nella repo non c'è codice che la generi, e i progetti nuovi non compaiono finché non viene rifatta | [Pagina Concept](02-dashboard/pagina-concept.md#parti-statiche-da-tenere-allineate-a-mano), [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md#d4-aggiornare-le-parti-statiche-della-dashboard) |

### Decisioni future

| # | Cosa | Dove compare |
|---|---|---|
| 8 | **Rotazione dei programmi quadro**: dare un nome e un codice al nuovo programma (in `update_db.py` e nella dashboard) e decidere se rimuovere, oscurare o tenere il programma più vecchio | [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md#attenzione-rotazione-programmi-quadro) |
| 9 | **Frequenza degli aggiornamenti**: consigliato ogni 4-6 mesi, ma la decide chi gestisce la piattaforma | [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md#quando-aggiornare) |
