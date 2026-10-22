# Review dei topic

> **Scopo:** spiega come si assegnano i topic ai progetti nuovi, come si svolge la revisione interattiva dei possibili topic nuovi, come si spostano i progetti già presenti nel db sui topic creati e perché il sistema funziona così. La prima parte è il runbook (cosa fare), la seconda la teoria (perché).

La review dei topic è il passo di `update_db.py` (step 1) in cui una persona decide cosa fare dei progetti nuovi che **non assomigliano abbastanza a nessun topic esistente**. È l'unica parte dell'aggiornamento che richiede un giudizio umano. Il resto della procedura è in [Eseguire l'aggiornamento dei dati](eseguire-update-db.md).

Il codice è in `data_update/`: `extract_topic.py` (assegnazione e report), `topic_review.py` (logica) e `topic_review_cli.py` (schermate a terminale). `reassign_existing.py` sposta progetti già presenti.

---

# Parte 1. Runbook

## 1.1 Prima di cominciare

- **Un terminale interattivo.** La review parte solo se `stdin` è un terminale. In uno script, con l'output rediretto o in un job automatico il sistema usa la modalità senza review (ogni progetto tiene il topic più vicino, vedi 1.10).
- **Gli embedding dei progetti nuovi sono pronti** (Specter2 e bge-m3, vedi P4 in [Eseguire l'aggiornamento dei dati](eseguire-update-db.md)).
- **`data/specter2.parquet` esiste.** Senza, i progetti già nel db non possono essere spostati sui topic nuovi (compare un `WARNING`).
- **Il backup di `data/` è stato fatto** (vedi P6). La review modifica il modello dei topic e `topic2hier.json`, anche se prima salva una copia.
- **Tempo:** di solito non più di mezz'ora, ma dipende dal numero di candidati.
- Il file in cui si salvano le decisioni è `decisions_file` in `settings.config` (default `new_data/topic_decisions.json`).

## 1.2 Avvio

La review fa parte dello step 1, quindi si avvia con:

```bash
python update_db.py              # tutti gli step
python update_db.py --projects   # solo progetti (e quindi review)
```

Prima della review il programma assegna a ogni progetto nuovo il topic esistente più simile e stampa:

```
N new projects assigned to existing topics.
M have similarity < 0.92: K candidate new topics, I isolated projects.
Review the candidates in new_data/topic_candidates.csv
```

- **Candidati**: i progetti la cui similarità con il topic più vicino è sotto la soglia (0,92).
- Il programma li raggruppa in **cluster** (K), ciascuno un possibile topic nuovo; quelli che non finiscono in nessun cluster sono **isolati** (I).
- Se ci sono meno di circa 12 candidati, non viene fatto nessun clustering e sono tutti isolati.
- Se non ci sono candidati stampa `No candidate new topics to review.` e prosegue senza review.

Il report dei candidati è un CSV (`candidates_report_file`, default `new_data/topic_candidates.csv`) con una riga per candidato:

| Colonna | Significato |
|---|---|
| `cluster`, `cluster_size` | Cluster di appartenenza (`-1` = isolato) e dimensione |
| `cluster_keywords` | Parole chiave del cluster |
| `projectID`, `title` | Il progetto |
| `similarity` | Similarità con il miglior topic originale |
| `nearest_topic` | Il topic più vicino |
| `auto_assigned` | `True` se il progetto è stato già assegnato automaticamente a un topic creato in una review precedente |

Il file serve per consultazione (si può aprire con un foglio di calcolo): le decisioni si prendono nelle schermate a terminale.

## 1.3 Come si svolge la sessione

La sessione interattiva segue sempre quest'ordine:

1. **Cluster**, uno alla volta, dal più grande al più piccolo.
2. **Progetti isolati.**
3. **Progetti già nel db**: solo per i topic che hai accettato come nuovi.
4. **Riepilogo** e conferma finale.

Ogni risposta viene salvata subito nel file delle decisioni. Un progetto non viene mai mostrato due volte.

## 1.4 Un cluster

La schermata mostra:

- il numero di progetti e la **similarità media** con il topic più vicino;
- le **parole chiave** del cluster;
- i **nomi suggeriti** (bigrammi frequenti nei titoli e parole chiave);
- i **5 progetti più rappresentativi** (titolo, similarità e topic più vicino);
- i **5 topic esistenti più simili** al cluster, con la similarità (una ★ segnala i topic creati in una review precedente).

Poi chiede cosa fare:

| Scelta | Che cosa fa |
|---|---|
| **Accetta come nuovo topic** | Crea un topic nuovo con i progetti del cluster (vedi 1.5). |
| **Rimappa su un topic esistente** | I progetti vanno a un topic già presente; il modello e la gerarchia non cambiano. Si sceglie tra i più simili o con la ricerca per nome. |
| **Unlabelled** | I progetti diventano `Unlabelled`. Il gruppo entra nel modello come *alias* con percorso vuoto: i progetti simili dei prossimi aggiornamenti verranno scartati in automatico. |
| **Tieni a ogni progetto il topic più vicino** | Nessun cambiamento: ciascuno resta dov'è. |
| **Escludi alcuni progetti dal cluster** | Si spuntano i progetti che non c'entrano: tengono il topic più vicino, il resto del cluster va avanti. |
| **Mostra tutti i progetti** | Elenca titolo e obiettivo (primi 400 caratteri) di ogni progetto. |
| **Decidi dopo** | Rimanda il cluster in fondo alla coda. |

Se il topic più simile è stato creato in una review precedente, il programma propone di rimapparlo lì, perché di solito il cluster tratta lo stesso tema.

> **Criteri di decisione: da completare.** Quando conviene accettare, rimappare o lasciare Unlabelled; con quali segnali (dimensione, titoli, vicinanza a un topic esistente) si giudica.

## 1.5 Accettare un nuovo topic

1. **Nome.** Il programma propone il primo nome suggerito. Si può scrivere un altro nome; un invio a vuoto torna indietro. Il nome non può essere `Unlabelled`. Controlli:
   - se **esiste già un topic con lo stesso nome**, propone di rimapparlo lì (o di scegliere un altro nome);
   - se il nome è già **una categoria** (un nodo con figli), va scelto un altro nome;
   - se è **simile a nomi già presenti**, mostra quali e chiede conferma.
2. **Posizione nella gerarchia.** Si naviga dalla radice: si sceglie una macro-area, poi eventualmente un'area e una sotto-area, e infine **Inserisci qui**. Si può creare una **nuova** macro-area, area o sotto-area scrivendone il nome. Il programma propone di partire accanto al topic più simile. Alla fine chiede conferma.
3. **Regole del percorso** (controllate dal programma):
   - il percorso ha da 2 a 4 nodi (macro-area, fino a due livelli intermedi, topic);
   - un topic è sempre una **foglia**: non può avere figli;
   - ogni nodo ha **un solo padre** e nello stesso percorso un nome non si ripete;
   - un percorso identico a uno esistente non è ammesso (si usa la rimappatura).

I topic accettati sono utilizzabili subito come destinazione di una rimappatura nella stessa sessione.

## 1.6 Progetti isolati

Dopo i cluster il programma chiede cosa fare dei progetti isolati:

- **Tieni a tutti il topic più vicino** (di solito la scelta ovvia), oppure
- **Rivedili uno per uno**: per ciascuno si sceglie tra tenere il topic più vicino, rimappare su un altro topic o `Unlabelled`. Per un progetto isolato `Unlabelled` vale solo per quel progetto, senza creare un alias nel modello.

## 1.7 Progetti già nel db

Per ogni topic che hai **accettato** come nuovo, il programma calcola quanti progetti **già presenti nel db** passerebbero lì (tra quelli sotto soglia) e mostra:

- il numero di progetti che si sposterebbero e il **bonus** usato;
- una tabella dei **topic di provenienza** (i primi 8);
- **10 esempi**, dal più sicuro al più incerto, con il margine (la differenza di similarità con il miglior topic originale).

Poi si sceglie:

| Scelta | Effetto |
|---|---|
| **Applica (N progetti)** | Salva il bonus e sposta quei progetti. |
| **Cambia il bonus…** | Si inserisce un altro valore tra −0,1 e +0,1 e si ricalcola. |
| **Mostra tutti i progetti** | Elenco completo (compare se sono più di 10). |
| **Non toccare i progetti già nel db** | Il topic nuovo prende solo progetti nuovi. |

**Il bonus** regola quanto è permissivo lo spostamento. Il valore proposto è `reviewed_topic_bonus_existing` (−0,005): una **penalità**, perché i progetti già nel db erano stati classificati in passato e conviene muoverne pochi. Più il bonus è alto, più progetti si spostano e più alto è il rischio di spostare progetti fuori tema; per i progetti nuovi il bonus è +0,02 (vedi la teoria). Solo i topic **accettati** prendono progetti già nel db, mai gli alias `Unlabelled`.

La risposta si salva come `existing_bonus` nella decisione di accettazione: `null` (o l'assenza del campo) significa "non toccare".

## 1.8 Riepilogo e conferma

Il programma mostra una tabella con un'azione per riga (nuovo topic, rimappa, `Unlabelled`, topic più vicino), il numero di progetti e, per i nuovi topic, quanti progetti già nel db si sposterebbero. Poi chiede **"Applicare queste decisioni?"**.

- **Sì:**
  - se sono stati accettati topic o alias, il **modello dei topic** e `topic2hier.json` vengono aggiornati (dopo averne copiato la versione precedente in `data/backups/`);
  - i progetti nuovi vengono scritti con i topic decisi (step 1.4 di `update_db.py`);
  - i progetti già presenti vengono spostati (step 1.6): vengono riscritti soltanto `topic_name` e `topic_name_hierarchy` dei progetti spostati, in `projects_uncase` e in `participants`, con un log in `data/backups/reassign_<data-ora>.json`;
  - `specter2.parquet`, i grafi dei progetti e la treemap vengono aggiornati.
- **No** (oppure Ctrl-C): non viene scritto nulla. Le decisioni restano nel file e si può riprendere.

## 1.9 Interrompere e riprendere

- Le decisioni vengono salvate nel file dopo **ogni risposta**. Se la sessione si interrompe (Ctrl-C, chiusura del terminale), nulla è stato scritto nel db.
- Rilanciando `update_db.py` per lo **stesso batch** di progetti, il programma trova il file e chiede: *"Trovate N decisioni salvate per questo batch. Riprendere da lì?"*. Rispondendo sì riparte dal punto in cui eri.
- Il file è legato al batch tramite un identificatore calcolato sugli id dei progetti nuovi. Se il batch è diverso, il file viene **sovrascritto** all'inizio della nuova sessione: se contiene decisioni che vuoi conservare, copialo prima.

## 1.10 Senza review e riapplicando decisioni

| Modo | Comando | Effetto |
|---|---|---|
| Senza review | `python update_db.py --no-review` | Ogni progetto tiene il topic esistente più vicino. Nessun topic nuovo. Il comportamento è lo stesso se non c'è un terminale. |
| Riapplicare decisioni | `python update_db.py --decisions FILE` | Applica le decisioni di quel file senza domande. Se il file è di un altro batch c'è un avviso e le decisioni valgono solo per i progetti che combaciano: non usare il file di un aggiornamento diverso. |

## 1.11 Spostare progetti già presenti: `reassign_existing.py`

Nel flusso normale lo spostamento dei progetti già presenti avviene dentro la review (1.7). `reassign_existing.py` serve per **topic accettati in revisioni passate**, per esempio prima che esistesse `data/specter2.parquet`. Riapplica la stessa schermata e la stessa regola a topic che esistono già.

```bash
python reassign_existing.py --topics 203 204 --dry-run   # mostra soltanto cosa cambierebbe
python reassign_existing.py --topics 203                 # interattivo: chiede cosa fare per ogni topic
python reassign_existing.py --topics 203 --bonus -0.005 --yes   # applica senza chiedere
```

| Opzione | Significato |
|---|---|
| `--topics ID [ID ...]` | Id dei topic (obbligatorio) |
| `--bonus X` | Bonus; se manca, quello di `settings.config` (`reviewed_topic_bonus_existing`) |
| `--dry-run` | Solo anteprima |
| `--yes` | Applica con `--bonus` senza domande |
| `--config FILE` | Altro `settings.config` |

Note:

- Funziona solo per topic creati da una review (elencati in `data/old_topic_model/reviewed_topics.json`). I topic originali non si riassegnano; un alias `Unlabelled` non prende progetti.
- Senza terminale richiede `--yes` o `--dry-run`.
- Alla fine rigenera i grafi dei progetti e la treemap e stampa il percorso del log.
- Un'interruzione con Ctrl-C non scrive nulla.

## 1.12 Cosa viene scritto e dove restano i backup

| Cosa | Dove | Quando |
|---|---|---|
| Nuovi topic nel modello | `data/old_topic_model/` | Se la review accetta topic o alias |
| Id dei topic creati da una review | `data/old_topic_model/reviewed_topics.json` | Stesso momento |
| Gerarchia | `data/topic2hier.json` | Stesso momento |
| Backup di modello e gerarchia | `data/backups/old_topic_model_<data-ora>/` e `topic2hier_<data-ora>.json` | Prima di ogni modifica del modello |
| Log degli spostamenti | `data/backups/reassign_<data-ora>.json` | Se vengono spostati progetti già presenti; contiene i topic di prima e la versione delle tabelle prima della modifica |
| Decisioni | `decisions_file` (default `new_data/topic_decisions.json`) | Dopo ogni risposta |
| Report dei candidati | `candidates_report_file` | Prima della review |

> **Ripristino: da completare.** Come tornare indietro (modello e gerarchia dalle copie in `data/backups/`, tabelle dalla versione indicata nel log) andrà descritto nella sezione sulle verifiche e il rollback.

Un dettaglio utile dal codice: il modello e la gerarchia vengono salvati **prima** che i progetti siano scritti nel db. Se `update_db.py` si interrompe tra i due momenti, il modello contiene già i topic nuovi mentre i progetti non sono ancora stati aggiunti; rilanciando, i progetti simili sono assegnati in automatico ai topic creati (`auto_assigned`).

## 1.13 Problemi comuni

| Sintomo | Causa e rimedio |
|---|---|
| La review non parte e ogni progetto prende il topic più vicino | Il terminale non è interattivo, oppure è stato passato `--no-review`. |
| `WARNING: ... not found: projects already in the db will not be reassigned` | Manca `data/specter2.parquet`: si può ricostruire con `compute_embeddings.py --model specter2 --source db` (vedi la parte 2). |
| `WARNING: N projects in the db have no Specter2 embedding` | Alcuni progetti nel db non hanno l'embedding nell'archivio e non possono essere spostati. |
| `... was written for a different batch` | Si sta usando un file di decisioni di un altro aggiornamento. |
| `Review cancelled: nothing was written` | Hai risposto no al riepilogo finale: le decisioni sono salvate, rilancia e riprendi. |
| Errore sul percorso di un nuovo topic (`un topic deve avere da 2 a 4 livelli`, `ogni nodo ha un solo padre`, ...) | Il percorso viola una regola della gerarchia (1.5). |

---

# Parte 2. Come funziona e perché

## 2.1 Il modello dei topic

- `data/old_topic_model/` contiene un modello **BERTopic** salvato in formato safetensors, **senza UMAP né HDBSCAN**. Per assegnare un progetto basta confrontarlo con i vettori dei topic.
- Ogni topic è rappresentato da un vettore (`topic_embeddings_`); l'id del topic è la sua riga (la prima riga è il topic degli outlier, `-1`).
- Un progetto va al topic con la **similarità coseno più alta** tra il suo embedding Specter2 e quello del topic (`assign_existing_topics`). È lo stesso risultato che darebbe `BERTopic.transform` per un modello fatto così.
- I topic originali vengono dal topic modeling sull'intero corpus (BERTopic con HDBSCAN e Specter2, tassonomia a quattro livelli costruita con approccio human-in-the-loop e clustering agglomerativo, etichette generate da un LLM: vedi la [Pagina Concept](../02-dashboard/pagina-concept.md)). 

## 2.2 La soglia di 0,92

Con Specter2 **ogni** progetto ha similarità alta (oltre 0,9) con quasi tutti i topic: lo spazio degli embedding è molto compresso. Per questo una similarità qualunque non dice nulla; serve una soglia alta. Sotto **0,92** (`similarity_threshold`) il progetto è considerato "poco simile al suo topic più vicino" e diventa un candidato a un topic nuovo.

## 2.3 Candidati e cluster

I candidati vengono raggruppati con UMAP (5 componenti, 10 vicini, distanza coseno) e HDBSCAN (`min_cluster_size`, default 5). Le parole chiave di ogni cluster sono le più caratteristiche secondo BERTopic (c-TF-IDF con stop word inglesi). Il clustering richiede un numero minimo di candidati: sotto circa 12 sono tutti isolati.

## 2.4 Topic creati da una review: bonus +0,02

I topic originali sono centroidi di **centinaia** di progetti e, nello spazio compresso di Specter2, funzionano da "hub": attirano quasi tutto. Un topic nuovo, centroide di pochi progetti, perderebbe sempre, anche per i suoi stessi progetti.

La regola: i topic creati da una review concorrono **solo per i progetti sotto soglia** e vincono se la loro similarità è almeno quella del miglior topic originale meno `reviewed_topic_bonus` (**0,02**). I progetti sopra soglia restano ai topic originali.

## 2.5 Perché non si usa `merge_models`

BERTopic ha una funzione per unire modelli (`merge_models`), ma non viene usata. Con Specter2 ogni similarità supera 0,9, quindi il suo `min_similarity` unirebbe quasi ogni topic nuovo a uno vecchio. I topic accettati e gli alias vengono invece aggiunti direttamente al modello: il centroide dei progetti come vettore del topic e una riga c-TF-IDF per le parole chiave.

## 2.6 Alias `Unlabelled`

Scegliere `Unlabelled` su un cluster aggiunge un topic al modello con percorso vuoto: serve a "assorbire" i progetti simili nei prossimi aggiornamenti, perché finiscano `Unlabelled` in automatico invece di tornare in review. Per i progetti isolati rivisti uno per uno, `Unlabelled` non crea alias.

## 2.7 Progetti già nel db: perché una penalità

Un topic accettato può prendere anche progetti già classificati. Con lo stesso criterio dei progetti nuovi ma un bonus più severo, `reviewed_topic_bonus_existing` (**−0,005**, cioè una penalità). 

I topic creati da review precedenti concorrono con lo stesso bonus: se uno di loro vince su un progetto già nel db, il progetto resta dov'è. Gli spostamenti riscrivono **solo** `topic_name` e `topic_name_hierarchy` dei progetti spostati; gli altri progetti non vengono mai riscritti.

## 2.8 Formato di `topic2hier.json`

- Ogni id di topic corrisponde a una lista di **4 nomi, dalla foglia alla macro-area**, allineati a destra con `Unlabelled`. Esempio: `["Unlabelled", "Climate Modelling", "Climatology", "Earth & Life Science"]` è un percorso di 3 livelli.
- Il nome mostrato (`topic_name`) è il primo nome non `Unlabelled`.
- Più id possono condividere lo stesso percorso (alias: per esempio 87 e 112, "RNA Biology").
- Regole dell'albero (`Hierarchy.validate_new_path`): ogni nodo ha un solo padre, i topic sono sempre foglie, un percorso ha da 2 a 4 nodi.
- Ogni topic del modello deve avere una voce, altrimenti i suoi progetti restano senza nome.
- Le macro-aree attuali sono cinque: Earth & Life Science, Engineering & Technology, Health & Medicine, Physical & Mathematical Sciences, Social Sciences & Humanities.

## 2.9 Parametri (`[topics]` in `settings.config`)

| Parametro | Default | Significato |
|---|---|---|
| `similarity_threshold` | 0.92 | Sotto questa similarità un progetto è candidato a un topic nuovo |
| `min_cluster_size` | 5 | Dimensione minima di un cluster di candidati |
| `candidates_report_file` | `new_data/topic_candidates.csv` | Report dei candidati |
| `decisions_file` | `new_data/topic_decisions.json` | Decisioni salvate |
| `reviewed_topic_bonus` | 0.02 | Bonus dei topic creati da una review, per i progetti nuovi |
| `reviewed_topic_bonus_existing` | −0.005 | Bonus (penalità) per i progetti già nel db |

## 2.10 Archivio degli embedding Specter2

`data/specter2.parquet` (colonne `projectID` int32 e `vector` fixed_size_list<float>[768]) contiene l'embedding Specter2 di **ogni** progetto del db. Serve solo ai topic: permette di valutare quali progetti già presenti passerebbero a un topic nuovo. `update_db.py` vi aggiunge i progetti nuovi a ogni aggiornamento (step 1.5); se il file manca, viene creato con i soli progetti nuovi. Gli embedding bge-m3 non hanno un archivio separato: sono `projects_uncase.vector`.

Se l'archivio va ricostruito dall'intero db:

```bash
python compute_embeddings.py --model specter2 --source db
```

(per default scrive in `../backup data/specter2.parquet`; poi va copiato in `data/specter2.parquet`). Il file deve avere lo schema atteso: se lo si scrive con pandas, `projectID` e `vector` possono avere tipi diversi; la scrittura con pyarrow tiene lo schema giusto.

---

## Pagine collegate

- [Eseguire l'aggiornamento dei dati](eseguire-update-db.md)
- [Pagina Concept](../02-dashboard/pagina-concept.md): la treemap della tassonomia, che si rigenera dopo ogni review.
