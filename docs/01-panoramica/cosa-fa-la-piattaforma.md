# Cosa fa la piattaforma

> **Scopo:** spiega a cosa serve la piattaforma, a chi si rivolge e quali dati contiene.

## In breve

Research Intelligence è una web app (Plotly Dash) costruita sul database **CORDIS**, il sistema informativo dell'Unione Europea sui progetti finanziati dai programmi quadro di ricerca.

Serve a due cose:

1. **Individuare potenziali partner** per una proposta di progetto: chi ha già lavorato su temi simili, in quali paesi, con quali organizzazioni.
2. **Valutare una proposta** rispetto a quanto l'UE ha già finanziato: esistono progetti simili? Quanti? Con quali consorzi?

## A chi si rivolge

- **Ricercatori**, che cercano partner e vogliono capire il panorama sul proprio tema.
- **Uffici di supporto ai progetti**, che valutano le proposte e preparano i consorzi.

## Come si lavora, in sintesi

L'utente restringe la ricerca con dei **filtri** (programma quadro, paese, tipo e nome di organizzazione, topic, coordinatore) e/o con un **testo libero**: un titolo, un argomento, o l'intero testo di una proposta. Il testo viene confrontato per significato (ricerca semantica) con gli obiettivi dei progetti.

I risultati si guardano in tre modi:

| Tab | Cosa mostra |
|---|---|
| Lista progetti | I progetti trovati, con partecipanti, deliverables e pubblicazioni |
| Vista aggregata | Il contributo di paesi, tipi di organizzazione, organizzazioni e topic al panorama trovato |
| Grafo dei progetti | Chi collabora con chi, raggruppato per topic |

I risultati si possono scaricare in CSV. Una seconda pagina, **Concept**, mostra la tassonomia dei topic. L'uso è descritto in [la sezione Dashboard](../02-dashboard/pagina-query.md).

## Quali dati contiene

- **Fonte:** l'export open data di CORDIS (<https://cordis.europa.eu/projects>, sezione "Download projects as open data"). 
- **Programmi quadro coperti:** solo i due più recenti, cioè quello in corso e quello immediatamente precedente. Oggi sono **Horizon Europe** (in corso) e **Horizon 2020** (precedente). 
- **Che cosa c'è per ogni progetto:** titolo, obiettivo, acronimo, programma, topic, organizzazioni partecipanti, deliverables e pubblicazioni.
- **Origine dei metadati arricchiti:**
  - i topic sono calcolati dalla piattaforma (BERTopic su embedding Specter2), vedi [Review dei topic](../03-aggiornamento-dati/review-topic.md#21-il-modello-dei-topic);
  - le pubblicazioni combinano CORDIS e Scopus;
  - i deliverables vengono da CORDIS. Gli autori, dove presenti, vengono da un'estrazione con un modello GenAI sui PDF, fatta con una pipeline a parte (vedi [Struttura dei dati](struttura-dati.md#deliverables-e-publications)).

## Pagine collegate

- [Architettura](architettura.md): com'è fatto il codice.
- [Eseguire l'aggiornamento dei dati](../03-aggiornamento-dati/eseguire-update-db.md): come si carica un nuovo export.
