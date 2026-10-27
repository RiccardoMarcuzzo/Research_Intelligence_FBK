# Review dei topic

> **Scopo:** spiega come si assegnano i topic ai progetti nuovi, come si compila il foglio Excel con cui una persona rivede i possibili topic nuovi, come i progetti già presenti nel db passano ai topic creati e perché il sistema funziona così. La prima parte è il runbook (cosa fare), la seconda la teoria (perché).

La review dei topic è la parte di `update_db.py` (step 1) in cui una persona decide cosa fare dei progetti nuovi che **non assomigliano abbastanza a nessun topic esistente**. È l'unica parte dell'aggiornamento che richiede un giudizio umano. Il resto della procedura è in [Eseguire l'aggiornamento dei dati](eseguire-update-db.md).

**Chi fa la review non ha bisogno di un terminale, e l'aggiornamento non aspetta la review.** Il processo è in tre momenti:

1. chi esegue l'aggiornamento lancia `python update_db.py` come sempre: **vengono eseguiti tutti gli step**. I progetti nuovi entrano nel db con un **topic provvisorio** e viene scritto un foglio Excel con la data nel nome (1.2);
2. il revisore compila il foglio (1.3-1.6), senza toccare il codice;
3. chi esegue l'aggiornamento lancia `python update_db.py --review FILE` e i topic decisi vengono applicati ai progetti già presenti nel db (1.7).

Fino al terzo momento la piattaforma è in uno stato consistente, solo con topic provvisori per i progetti candidati.

Il codice è in `data_update/`: `extract_topic.py` (assegnazione, topic provvisori, applicazione del foglio), `topic_review.py` (logica: gerarchia, modello, spostamenti) e `topic_review_sheet.py` (scrittura e lettura del foglio).

---

# Parte 1. Runbook

## 1.1 Prima di cominciare

- **Gli embedding dei progetti nuovi sono pronti** (Specter2 e bge-m3, vedi P4 in [Eseguire l'aggiornamento dei dati](eseguire-update-db.md)).
- **`data/specter2.parquet` esiste.** `--review` ne ha bisogno per leggere gli embedding dei progetti del foglio e per spostare i progetti vecchi sui topic nuovi.
- **Il backup di `data/` è stato fatto** (vedi P6). Applicare il foglio modifica il modello dei topic e `topic2hier.json`, anche se prima ne salva una copia.

## 1.2 Il lancio normale: topic provvisori e foglio

```bash
python update_db.py              # tutti gli step
python update_db.py --projects   # solo progetti (e quindi topic e foglio)
```

Il programma assegna a ogni progetto nuovo il topic esistente più simile e stampa:

```
N new projects assigned to existing topics.
M have similarity < 0.92: K candidate new topics, I isolated projects.
Review sheet: K clusters, I isolated projects.
Fill in new_data/topic_review_2026-10-26.xlsx, then apply it with: python update_db.py --review new_data/topic_review_2026-10-26.xlsx
```

Poi **prosegue con tutti gli altri passaggi**. I progetti candidati hanno un **topic provvisorio**:

| Progetto | Topic provvisorio |
|---|---|
| Non candidato (similarità ≥ 0,92) | Il topic esistente più simile, come sempre |
| Candidato in un cluster | **Lo stesso topic per tutto il cluster**: quello più simile al centro del cluster |
| Candidato isolato | `Unlabelled` (senza alias nel modello) |
| Candidato già assegnato in automatico a un topic creato da una review precedente | Quel topic (`auto_assigned`): resta dov'è |

Il **modello dei topic e `topic2hier.json` non cambiano** in questo lancio: li modifica soltanto `--review`.

Il file ha il nome di `review_file` (default `new_data/topic_review.xlsx`) con la **data del lancio** prima dell'estensione. Un secondo lancio nello stesso giorno **sovrascrive** il foglio del giorno; in un giorno diverso i fogli **convivono**, ciascuno col suo gruppo di progetti. Se il foglio è già stato compilato conviene rinominarlo prima di rilanciare.

- **Candidati**: i progetti la cui similarità con il topic più vicino è sotto la soglia (0,92).
- Il programma li raggruppa in **cluster** (K), ciascuno un possibile topic nuovo; quelli che non finiscono in nessun cluster sono **isolati** (I).
- Se ci sono meno di circa 12 candidati, non viene fatto nessun clustering e sono tutti isolati (quindi `Unlabelled` in via provvisoria).
- Se non ci sono candidati stampa `No candidate new topics to review.` e non scrive nessun foglio.

## 1.3 Il foglio

| Foglio | Contenuto |
|---|---|
| **Istruzioni** | Come si compila. |
| **Indice** | Un cluster per riga (con collegamento al foglio), numero di progetti, parole chiave, topic esistente più simile e il **percorso già inserito** (si aggiorna da solo). |
| **Gerarchia** | I topic esistenti, uno per riga, con i quattro livelli. Serve a scegliere dove inserire. |
| **C01, C02, …** | Un foglio per cluster, dal più grande al più piccolo. |
| **Isolati** | I progetti che non stanno in nessun cluster. |

Ogni foglio cluster ha in cima le parole chiave, i **5 topic esistenti più simili** (con la similarità), le **celle gialle B4:E4** per il percorso e una cella per le note. Sotto c'è la tabella dei progetti, **ordinata dal più al meno rilevante** (il più vicino al centro del cluster per primo), con titolo, primi 600 caratteri dell'*objective*, **topic provvisorio** e la colonna **Altro topic**.

> **Non modificare** la colonna *projectID* né la colonna *Topic provvisorio*: servono a controllare, quando il foglio viene applicato, che i progetti siano ancora quelli.

## 1.4 Compilare un cluster

Si scrive il **percorso** del topic nelle celle gialle B4:E4: livello 1 (macro-area) in B4, poi uno per cella, fino a quattro. La cella B4 ha un menu con le macro-aree esistenti, ma si può scrivere anche un nome nuovo.

| Cosa si scrive | Che cosa succede |
|---|---|
| **Niente** | Ogni progetto del cluster resta al topic provvisorio. È il comportamento se si salta un cluster. |
| **Un percorso già presente nel foglio Gerarchia** | I progetti vanno a quel topic esistente; modello e gerarchia non cambiano. |
| **Un percorso nuovo** | Nasce un **topic nuovo** con quel percorso. Può stare sotto categorie esistenti o crearne di nuove. |
| **`Unlabelled`** nel livello 1 | I progetti diventano `Unlabelled`. Il gruppo entra nel modello come *alias* con percorso vuoto: i progetti simili dei prossimi aggiornamenti verranno scartati in automatico (2.6). |

Si può usare **qualunque** percorso, esistente o nuovo. I nomi già esistenti vengono riconosciuti anche con maiuscole diverse (e il programma avvisa che li ha corretti).

Un progetto che non c'entra con il percorso del cluster si tratta nella colonna **Altro topic** (E), che ha un menu con tutti i **topic esistenti** (foglie): si sceglie dal menu, oppure si digita e il menu filtra mentre si scrive. Il progetto va a quel topic, qualunque sia il percorso del cluster. Scrivendo una **x** (o cancellando la riga) il progetto resta invece al topic provvisorio. Il testo digitato deve essere esattamente il nome di un topic esistente (maiuscole a parte) oppure `x`: altrimenti è un errore. Il menu riguarda solo i topic esistenti; per un topic nuovo si usa il percorso del cluster o il foglio Isolati.

Tutti i progetti, di **qualunque foglio**, con lo stesso percorso nuovo formano **un solo topic**. Quindi due cluster che trattano lo stesso tema si uniscono scrivendo lo stesso percorso.

> **Criteri di decisione: da completare.** Quando conviene accettare, rimappare o lasciare Unlabelled; con quali segnali (dimensione, titoli, vicinanza a un topic esistente) si giudica.

## 1.5 Regole del percorso

Il programma le controlla alla lettura del foglio:

- il percorso ha da 2 a 4 livelli (macro-area, fino a due livelli intermedi, topic) e si riempie dal primo, **senza buchi**;
- un topic è sempre una **foglia**: non può avere figli, e un nome già usato come categoria non può diventare un topic;
- ogni nodo ha **un solo padre** e nello stesso percorso un nome non si ripete;
- `Unlabelled` va da solo nel livello 1;
- un nome nuovo **simile** a uno esistente (per esempio `Climate Modeling` e `Climate Modelling`) non è un errore ma genera un avviso: controllare che non sia un refuso.

## 1.6 Il foglio Isolati

Gli **isolati** sono progetti troppo poco simili a ogni topic esistente (sotto la soglia) e troppo diversi tra loro per formare un cluster. Per ora sono `Unlabelled`. L'intestazione del foglio lo ricorda: se un progetto non merita un topic proprio basta lasciarlo com'è.

Qui ogni progetto ha le **proprie** celle per il percorso (colonne E-H, stesse regole dei cluster). Lasciarle vuote significa che il progetto resta `Unlabelled`. Per dare un topic a un progetto si scrive un percorso; più isolati con lo stesso percorso nuovo formano un topic. Con `Unlabelled` su un isolato il progetto resta `Unlabelled` e basta: **non** si crea un alias nel modello, perché il centroide di progetti tra loro eterogenei assorbirebbe troppi progetti dei prossimi aggiornamenti.

## 1.7 Applicare il foglio: `--review`

Salvare il file (formato `.xlsx`) e lanciare:

```bash
python update_db.py --review new_data/topic_review_2026-10-26.xlsx
```

`--review` **applica il foglio e termina**: non legge l'export, non aggiunge progetti e non si combina con i flag degli step né con `--no-review`. Funziona sui progetti che sono **già nel db** (quelli del foglio).

Il programma **legge tutto il foglio e raccoglie tutti gli errori** prima di fare qualsiasi cosa, indicando foglio e cella:

```
new_data/topic_review_2026-10-26.xlsx contains 2 error(s):
  - C01: percorso Engineering & Technology > Arms: ...
  - C02!A20: projectID 999 non presente nel db
```

Controlla anche che ogni progetto abbia **ancora il topic provvisorio** scritto nel foglio. Se non è così, il foglio è già stato applicato (applicarlo due volte non è possibile) oppure il progetto è stato spostato da un'altra review; per lasciarlo com'è si cancella la sua riga.

Se ci sono errori, esce con `No database was modified.` e si corregge il foglio. Altrimenti applica:

1. i **topic nuovi** e gli alias entrano nel modello e in `topic2hier.json` (dopo averne copiato la versione precedente in `data/backups/`);
2. i progetti del foglio il cui topic cambia vengono riscritti (`topic_name` e `topic_name_hierarchy`, in `projects_uncase` e in `participants`);
3. i **progetti già presenti nel db** che somigliano a un topic nuovo passano a quel topic (1.8);
4. i grafi dei progetti e la treemap vengono rigenerati.

Tutte le riscritture di topic sono in un unico log, `data/backups/reassign_<data-ora>.json`, con i topic di prima e la versione delle tabelle prima della modifica.

## 1.8 Progetti già nel db

Ogni **topic nuovo** (non gli alias `Unlabelled`, non i topic esistenti) prende anche i progetti **già presenti nel db** che gli somigliano, senza che il revisore debba decidere. La regola è quella dei progetti nuovi, ma con una penalità fissa, `reviewed_topic_bonus_existing` (−0,005 di default): concorrono solo i progetti sotto soglia e vince il topic nuovo se la sua similarità, più il bonus, raggiunge quella del miglior topic originale. I progetti già classificati in passato si spostano quindi poco (vedi 2.7). Vengono riscritti soltanto `topic_name` e `topic_name_hierarchy` dei progetti spostati.

## 1.9 Senza review

```bash
python update_db.py --no-review
```

Ogni progetto tiene il topic esistente più vicino. Nessun foglio, nessun topic provvisorio nei cluster. `--review` e `--no-review` non si usano insieme.

## 1.10 Cosa viene scritto e dove restano i backup

| Cosa | Dove | Quando |
|---|---|---|
| Foglio da compilare | `review_file` con la data (es. `new_data/topic_review_2026-10-26.xlsx`) | Al lancio normale, se ci sono candidati |
| Nuovi topic nel modello | `data/old_topic_model/` | Con `--review`, se il foglio crea topic o alias |
| Id dei topic creati da una review | `data/old_topic_model/reviewed_topics.json` | Stesso momento |
| Gerarchia | `data/topic2hier.json` | Stesso momento |
| Backup di modello e gerarchia | `data/backups/old_topic_model_<data-ora>/` e `topic2hier_<data-ora>.json` | Prima di ogni modifica del modello |
| Log delle riscritture | `data/backups/reassign_<data-ora>.json` | Con `--review`; contiene i topic di prima e la versione delle tabelle prima della modifica |

> **Ripristino: da completare.** Come tornare indietro (modello e gerarchia dalle copie in `data/backups/`, tabelle dalla versione indicata nel log) andrà descritto nella sezione sulle verifiche e il rollback.

Un dettaglio utile dal codice: con `--review` il modello e la gerarchia vengono salvati **prima** che i progetti siano riscritti nel db. Se il programma si interrompe tra i due momenti, il modello contiene già i topic nuovi mentre i progetti hanno ancora i topic provvisori. Rilanciare `--review` con lo stesso foglio non è sicuro: un percorso nuovo è ormai un percorso esistente, quindi i progetti del foglio vengono assegnati a quei topic ma i progetti vecchi non si spostano e gli alias `Unlabelled` dei cluster verrebbero creati una seconda volta. Per un risultato pulito si ripristinano modello e gerarchia dal backup (`data/backups/`) e si rilancia.

## 1.11 Problemi comuni

| Sintomo | Causa e rimedio |
|---|---|
| Il lancio normale non si ferma e non chiede nulla | È il comportamento voluto: i progetti entrano con topic provvisori. Il foglio si applica dopo, con `--review`. |
| `contains N error(s)` | Il foglio ha errori: il messaggio indica foglio e cella. Nulla è stato scritto. |
| `ha ora il topic "X" nel db, non "Y": il foglio è già stato applicato o il progetto è stato spostato` | Il foglio è già stato applicato, oppure il progetto è cambiato dopo (o è stata modificata la colonna *Topic provvisorio*). Cancellare la riga di quel progetto per lasciarlo com'è. |
| `projectID ... non presente nel db` | Un projectID modificato a mano, oppure i progetti del foglio non sono stati scritti nel db (lancio interrotto). |
| `il progetto N compare anche in ...` | Lo stesso progetto è in due fogli. |
| `impossibile leggere ...` | Il file non è un `.xlsx` valido (per esempio salvato come CSV). |
| `Specter2 embeddings: ...` con `--review` | Mancano `data/specter2.parquet` o gli embedding di alcuni progetti del foglio: si può ricostruire con `compute_embeddings.py --model specter2 --source db` (vedi la parte 2). |
| `WARNING: ... not found: projects already in the db will not be reassigned` | Manca `data/specter2.parquet`: i progetti vecchi non si spostano sui topic nuovi. |
| `WARNING: N projects in the db have no Specter2 embedding` | Alcuni progetti nel db non hanno l'embedding nell'archivio e non possono essere spostati. |

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

Scrivere `Unlabelled` su un **cluster** aggiunge un topic al modello con percorso vuoto: serve a "assorbire" i progetti simili nei prossimi aggiornamenti, perché finiscano `Unlabelled` in automatico invece di tornare in review. Per i progetti **isolati** `Unlabelled` vale solo per quel progetto, senza alias.

## 2.7 Progetti già nel db: perché una penalità

Un topic nuovo prende anche progetti già classificati, sempre. Con lo stesso criterio dei progetti nuovi ma un bonus più severo, `reviewed_topic_bonus_existing` (**−0,005**, cioè una penalità). Un topic ampio come "Generative AI" (203) prenderebbe 760 progetti vecchi con +0,02 (molti fuori tema), 168 con 0 e circa 100 con −0,005. Il revisore non sceglie il bonus: lo fissa la configurazione. 

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
| `review_file` | `new_data/topic_review.xlsx` | Foglio Excel dei possibili topic nuovi; al nome viene aggiunta la data del lancio |
| `reviewed_topic_bonus` | 0.02 | Bonus dei topic creati da una review, per i progetti nuovi |
| `reviewed_topic_bonus_existing` | −0.005 | Bonus (penalità) con cui i topic nuovi prendono progetti già nel db |

## 2.10 Topic provvisori

Il lancio normale non aspetta la review perché i progetti nuovi devono essere nella piattaforma comunque. Finché il foglio non è applicato, un candidato ha un topic che sia **coerente col suo gruppo**: tutto il cluster va al topic più vicino al suo centroide (la stessa regola di `assign_existing_topics`, con i topic delle review precedenti che concorrono col bonus), perché il revisore decide per cluster; gli isolati sono `Unlabelled`, perché per definizione non hanno un topic vicino. I candidati già assegnati in automatico a un topic di una review precedente restano lì: sono già stati riconosciuti come simili a un topic rivisto. Il foglio riporta il topic provvisorio effettivo, e `--review` lo usa come controllo: un progetto il cui topic nel db è cambiato nel frattempo non viene sovrascritto.

## 2.11 Archivio degli embedding Specter2

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
