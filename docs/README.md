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

I numeri delle voci non cambiano quando altre vengono risolte (le voci 3-7 sono state completate il 2026-10-29).

### Documentazione da scrivere

| # | Cosa manca | Dove compare |
|---|---|---|
| 1 | **Deploy sul nuovo server** (non ancora fatto): dove gira l'app, come si avvia (servizio, container...), reverse proxy, valore di `--path`. I vincoli che vengono dal codice sono già scritti | [Avvio della dashboard](02-dashboard/avvio-dashboard.md#deploy) |
| 2 | **Criteri di decisione della review dei topic**: c'è una proposta, da validare con chi farà la review e poi da trasformare in regole | [Review dei topic](03-aggiornamento-dati/review-topic.md#criteri-di-decisione-proposta) |

### Operazioni da fare sui dati

| # | Cosa | Dove compare |
|---|---|---|
| 10 | **Primo lancio di `extract_deliverables.py`** sull'export del 2026-10-15, poi `update_db.py --deliverables` con `deliverables_file`: oggi i deliverables Horizon Europe nuovi sono senza autori | [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md#p3-estrarre-gli-autori-dei-deliverables-facoltativo) |

### Funzioni da definire o completare

| # | Cosa manca | Dove compare |
|---|---|---|
| 11 | **Pubblicazioni da una fonte esterna** (`publications_file`, per esempio una nuova estrazione Scopus con le affiliazioni): il parametro è riservato ma l'import non è implementato. Oggi le pubblicazioni dei progetti nuovi vengono dall'export CORDIS, senza affiliazioni | [Struttura dei dati](01-panoramica/struttura-dati.md#publications-step-4) |

### Decisioni future

| # | Cosa | Dove compare |
|---|---|---|
| 8 | **Rotazione dei programmi quadro**: dare un nome e un codice al nuovo programma (in `update_db.py` e nella dashboard) e decidere se rimuovere, oscurare o tenere il programma più vecchio | [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md#attenzione-rotazione-programmi-quadro) |
| 9 | **Frequenza degli aggiornamenti**: consigliato ogni 4-6 mesi, ma la decide chi gestisce la piattaforma | [Eseguire l'aggiornamento dei dati](03-aggiornamento-dati/eseguire-update-db.md#quando-aggiornare) |
