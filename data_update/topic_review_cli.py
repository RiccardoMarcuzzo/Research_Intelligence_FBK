# ------------------------------------------------------------------------------
# Interfaccia a terminale per la revisione dei possibili topic nuovi.
# La logica è in topic_review.py; qui ci sono solo schermate e domande.
# Ogni decisione viene salvata subito nel file delle decisioni: se la sessione si
# interrompe (Ctrl-C) niente viene scritto nei db e la revisione si può riprendere.
# ------------------------------------------------------------------------------

import os

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from topic_review import (UNLABELLED, DEPTH, DecisionStore, HierarchyError, ReviewAborted,
                          batch_key, check_name, similar_topics, summarize_clusters,
                          isolated_indices, accept_targets, existing_moves)

LEVEL_NAMES = ["macro-area", "area", "sotto-area"]
# limiti del bonus per i progetti già nel db (oltre ±0.1 la regola non ha senso)
BONUS_RANGE = (-0.1, 0.1)


def fmt_path(path):
    return " > ".join(path) if path else UNLABELLED


def _parse_bonus(value):
    try:
        bonus = float(str(value).replace(",", "."))
    except ValueError:
        return None
    return bonus if BONUS_RANGE[0] <= bonus <= BONUS_RANGE[1] else None


def show_existing_moves(console, moves, path, bonus, n_examples=10, all_titles=False):
    console.print(Panel(
        f"[bold]{len(moves)} progetti già nel db[/bold] passerebbero a [bold]{fmt_path(path)}[/bold] "
        f"(bonus {bonus:+.3f}: negativo = più severo).",
        title="Progetti già nel db", expand=False))
    if moves.empty:
        return
    sources = Table(title="Da quali topic arrivano")
    sources.add_column("Topic attuale", overflow="fold")
    sources.add_column("Progetti", justify="right")
    counts = moves["from_topic"].value_counts()
    for name, n in counts.head(8).items():
        sources.add_row(name, str(n))
    if len(counts) > 8:
        sources.add_row(f"altri {len(counts) - 8} topic", str(counts.iloc[8:].sum()))
    console.print(sources)

    # esempi distribuiti dal più sicuro al più incerto, così si vede anche il margine
    if all_titles or len(moves) <= n_examples:
        rows = list(range(len(moves)))
    else:
        rows = sorted({round(i * (len(moves) - 1) / (n_examples - 1)) for i in range(n_examples)})
    examples = Table(title="Tutti i progetti" if all_titles else "Esempi, dal più sicuro al più incerto")
    examples.add_column("Titolo", overflow="fold")
    examples.add_column("Topic attuale", overflow="fold")
    examples.add_column("Margine", justify="right")
    for i in rows:
        m = moves.iloc[i]
        examples.add_row(str(m["title"]), m["from_topic"], f"{m['similarity'] - m['best_original']:+.3f}")
    console.print(examples)


def ask_existing_bonus(prompter, console, path, compute, bonus):
    """Mostra quali progetti già nel db passerebbero al topic e chiede cosa fare.
    compute(bonus) restituisce gli spostamenti. Restituisce il bonus scelto o None
    (i progetti già nel db non vengono toccati)."""
    all_titles = False
    while True:
        moves = compute(bonus)
        show_existing_moves(console, moves, path, bonus, all_titles=all_titles)
        all_titles = False
        choices = [(f"Applica ({len(moves)} progetti)", "apply"),
                   ("Cambia il bonus…", "change")]
        if len(moves) > 10:
            choices.append(("Mostra tutti i progetti", "details"))
        choices.append(("Non toccare i progetti già nel db", "skip"))
        action = prompter.select("Cosa vuoi fare con i progetti già nel db?", choices)
        if action == "apply":
            return bonus
        if action == "skip":
            return None
        if action == "details":
            all_titles = True
        elif action == "change":
            value = prompter.text(
                f"Nuovo bonus, tra {BONUS_RANGE[0]} e {BONUS_RANGE[1]} (negativo = più severo):",
                default=f"{bonus:+.3f}",
                validate=lambda v: _parse_bonus(v) is not None or "numero non valido")
            if _parse_bonus(value) is not None:
                bonus = _parse_bonus(value)


class QuestionaryPrompter:
    """Domande a terminale. Le scelte sono coppie (testo, valore)."""

    def __init__(self):
        import questionary
        self.q = questionary

    def _choices(self, choices):
        return [self.q.Choice(title, value=value) for title, value in choices]

    def select(self, message, choices, default=None):
        cs = self._choices(choices)
        default = next((c for c in cs if c.value == default), None)
        return self.q.select(message, choices=cs, default=default).unsafe_ask()

    def checkbox(self, message, choices):
        return self.q.checkbox(message, choices=self._choices(choices)).unsafe_ask()

    def text(self, message, default="", validate=None):
        return self.q.text(message, default=default, validate=validate).unsafe_ask()

    def autocomplete(self, message, choices):
        return self.q.autocomplete(
            message, choices=choices, match_middle=True,
            validate=lambda v: v == "" or v in choices or "scegli un elemento dell'elenco",
        ).unsafe_ask()

    def confirm(self, message, default=True):
        return self.q.confirm(message, default=default).unsafe_ask()


class Reviewer:
    def __init__(self, ctx, store, prompter, console):
        self.ctx = ctx
        self.store = store
        self.p = prompter
        self.c = console
        # copia della gerarchia che include i topic accettati in questa sessione,
        # così si possono usare subito come destinazione di una rimappatura
        self.hier = ctx.hierarchy.copy()
        self._provisional = -1000
        for d in store.decisions:
            self._track(d)

    # --- utilità -----------------------------------------------------------------
    def _track(self, decision):
        if decision["action"] == "accept":
            self._provisional -= 1
            self.hier.paths[self._provisional] = tuple(decision["path"])

    def decide(self, decision):
        self.store.add(decision)
        self._track(decision)

    def ids(self, indices):
        return [int(self.ctx.project_ids[i]) for i in indices]

    def nearest_path(self, i):
        return self.ctx.hierarchy.path(self.ctx.topics[i])

    # --- schermate ---------------------------------------------------------------
    def show_cluster(self, c, number, total):
        head = (f"[bold]{len(c.indices)} progetti[/bold] · similarità media con il topic più vicino "
                f"{c.mean_similarity:.3f}\n[bold]Parole chiave:[/bold] {c.keywords or '-'}\n"
                f"[bold]Nomi suggeriti:[/bold] {', '.join(c.name_suggestions) or '-'}")
        self.c.print(Panel(head, title=f"Cluster {number}/{total}", expand=False))

        projects = Table(title="Progetti più rappresentativi", show_lines=False)
        projects.add_column("Titolo", overflow="fold")
        projects.add_column("Sim.", justify="right")
        projects.add_column("Topic più vicino", overflow="fold")
        for i in c.indices[:5]:
            projects.add_row(self.ctx.titles[i], f"{self.ctx.similarity[i]:.3f}", fmt_path(self.nearest_path(i)))
        self.c.print(projects)

        topics = Table(title="Topic esistenti più simili (★ = creato in una revisione precedente)")
        topics.add_column("#", justify="right")
        topics.add_column("Percorso", overflow="fold")
        topics.add_column("Sim.", justify="right")
        for n, (topic_id, path, sim) in enumerate(c.similar_topics, 1):
            mark = " ★" if topic_id in self.ctx.reviewed_topics else ""
            topics.add_row(str(n), fmt_path(path) + mark, f"{sim:.3f}")
        self.c.print(topics)

    def show_projects(self, indices, objective_chars=400):
        for i in indices:
            objective = self.ctx.objectives[i] or ""
            if len(objective) > objective_chars:
                objective = objective[:objective_chars] + "…"
            self.c.print(Panel(objective, title=f"{self.ctx.titles[i]}  (sim. {self.ctx.similarity[i]:.3f})",
                               subtitle=f"topic più vicino: {fmt_path(self.nearest_path(i))}", expand=False))

    def show_summary(self):
        table = Table(title="Riepilogo delle decisioni")
        table.add_column("Azione")
        table.add_column("Progetti", justify="right")
        table.add_column("Dettaglio", overflow="fold")
        labels = {"accept": "nuovo topic", "remap": "rimappa", "unlabelled": "Unlabelled",
                  "nearest": "topic più vicino"}
        moved = self.existing_moves()["key"].value_counts().to_dict() if self.ctx.existing is not None else None
        for i, d in enumerate(self.store.decisions):
            detail = fmt_path(d["path"]) if d.get("path") else ""
            if d["action"] == "unlabelled":
                detail = "alias nel modello" if d.get("alias", True) else ""
            if d["action"] == "accept" and moved is not None:
                detail += f" · {int(moved.get(i, 0))} progetti già nel db"
            table.add_row(labels[d["action"]], str(len(d["project_ids"])), detail)
        self.c.print(table)

    # --- progetti già nel db -----------------------------------------------------
    def existing_moves(self, override=None):
        """Spostamenti dei progetti già nel db con le decisioni prese finora; i topic
        accettati ancora senza risposta usano il bonus proposto."""
        targets = accept_targets(self.store.decisions, self.ctx.project_ids, self.ctx.embeddings,
                                 default_bonus=self.ctx.existing_bonus, override=override)
        return existing_moves(self.ctx.model, self.ctx.reviewed_topics, self.ctx.existing, targets,
                              self.ctx.similarity_threshold, self.ctx.existing_bonus)

    def review_existing(self):
        if self.ctx.existing is None:
            return
        for i, d in enumerate(self.store.decisions):
            if d["action"] != "accept" or "existing_bonus" in d:
                continue

            def compute(bonus, i=i):
                moves = self.existing_moves(override={i: bonus})
                return moves[moves["key"] == i].reset_index(drop=True)

            bonus = ask_existing_bonus(self.p, self.c, d["path"], compute, self.ctx.existing_bonus)
            self.store.set_field(i, "existing_bonus", bonus)

    # --- domande -----------------------------------------------------------------
    def choose_existing(self, similar):
        while True:
            choices = [(f"{fmt_path(p)}  ({s:.3f})", ("path", p)) for _, p, s in similar]
            choices += [("Cerca per nome…", ("search", None)), ("↩ Indietro", ("back", None))]
            kind, path = self.p.select("Su quale topic esistente?", choices)
            if kind == "back":
                return None
            if kind == "path":
                return path
            by_label = {fmt_path(p): p for p in self.hier.leaves()}
            answer = self.p.autocomplete("Cerca un topic (vuoto per tornare indietro):", sorted(by_label))
            if answer:
                return by_label[answer]

    def ask_name(self, c):
        while True:
            default = c.name_suggestions[0] if c.name_suggestions else ""
            name = (self.p.text("Nome del nuovo topic (vuoto per tornare indietro):", default=default,
                                validate=lambda v: v.strip() != UNLABELLED or "nome riservato") or "").strip()
            if not name:
                return None
            exact, similar = check_name(name, self.hier)
            if exact:
                topics = sorted(p for p in self.hier.leaves() if p[-1] in exact)
                if topics:
                    self.c.print(f'[yellow]Esiste già un topic "{exact[0]}".[/yellow]')
                    choice = self.p.select("Cosa vuoi fare?",
                                           [(f"Rimappa su {fmt_path(p)}", ("remap", p)) for p in topics]
                                           + [("Scegli un altro nome", ("rename", None))])
                    if choice[0] == "remap":
                        return choice
                    continue
                self.c.print(f'[yellow]"{exact[0]}" è già una categoria della gerarchia: scegli un altro nome.[/yellow]')
                continue
            if similar:
                self.c.print(f"[yellow]Nomi simili già presenti: {', '.join(similar)}[/yellow]")
                if not self.p.confirm("Usare comunque questo nome?", default=False):
                    continue
            return ("name", name)

    def ask_new_category(self, prefix, topic_name):
        name = (self.p.text(f"Nome della nuova {LEVEL_NAMES[len(prefix)]} (vuoto per annullare):") or "").strip()
        if not name:
            return None
        if name == UNLABELLED or name == topic_name:
            self.c.print("[red]Nome non valido.[/red]")
            return None
        if name in self.hier.node_names():
            self.c.print(f'[red]"{name}" esiste già nella gerarchia (ogni nodo ha un solo padre).[/red]')
            return None
        return name

    def choose_path(self, c, name):
        proposal = c.similar_topics[0][1][:-1] if c.similar_topics else ()
        self.c.print(f"Proposta: accanto a [bold]{fmt_path(c.similar_topics[0][1])}[/bold]"
                     if c.similar_topics else "Scegli dove inserire il topic.")
        prefix = ()
        while True:
            depth = len(prefix)
            options = []
            if depth >= 1:
                options.append((f"➕ Inserisci qui: {fmt_path(prefix + (name,))}", ("here", None)))
            if depth < DEPTH - 1:
                options += [(n, ("child", n)) for n in self.hier.children(prefix)]
                options.append((f"✚ Nuova {LEVEL_NAMES[depth]}…", ("new", None)))
            options.append(("↩ Indietro" if depth else "↩ Annulla", ("back", None)))

            if proposal[:depth] == prefix and len(proposal) > depth:
                default = ("child", proposal[depth])
            elif proposal == prefix and depth >= 1:
                default = ("here", None)
            else:
                default = None
            where = fmt_path(prefix) if prefix else "Radice"
            level = LEVEL_NAMES[depth] if depth < DEPTH - 1 else "posizione"
            kind, value = self.p.select(f"{where} — scegli la {level}", options, default=default)

            if kind == "back":
                if not prefix:
                    return None
                prefix = prefix[:-1]
            elif kind == "child":
                prefix = prefix + (value,)
            elif kind == "new":
                new = self.ask_new_category(prefix, name)
                if new:
                    prefix = prefix + (new,)
            elif kind == "here":
                path = prefix + (name,)
                try:
                    self.hier.validate_new_path(path)
                except HierarchyError as e:
                    self.c.print(f"[red]{e}[/red]")
                    continue
                if self.p.confirm(f"Inserire il topic in {fmt_path(path)}?", default=True):
                    return path

    # --- flusso ------------------------------------------------------------------
    def review_cluster(self, c, number, total, allow_later=True):
        while True:
            self.show_cluster(c, number, total)
            choices = [
                ("Accetta come nuovo topic", "accept"),
                ("Rimappa su un topic esistente", "remap"),
                ("Unlabelled (anche i progetti simili dei prossimi batch)", "unlabelled"),
                ("Tieni a ogni progetto il topic più vicino", "nearest"),
                ("Escludi alcuni progetti dal cluster", "exclude"),
                ("Mostra tutti i progetti", "details"),
            ]
            if allow_later:
                choices.append(("Decidi dopo", "later"))
            # se il topic più simile è stato creato in una revisione precedente, di solito il
            # cluster è lo stesso tema: si propone di rimapparlo lì
            default = None
            if c.similar_topics and c.similar_topics[0][0] in self.ctx.reviewed_topics:
                default = "remap"
                self.c.print(f"[cyan]Il topic più simile, {fmt_path(c.similar_topics[0][1])}, è stato creato "
                             f"in una revisione precedente: probabilmente è lo stesso tema.[/cyan]")
            action = self.p.select("Cosa vuoi fare con questo cluster?", choices, default=default)
            base = {"project_ids": self.ids(c.indices), "cluster": c.cluster, "keywords": c.keywords}

            if action == "later":
                return "later"
            if action == "details":
                self.show_projects(c.indices)
            elif action == "exclude":
                excluded = self.p.checkbox("Progetti da escludere (terranno il topic più vicino):",
                                           [(self.ctx.titles[i], i) for i in c.indices])
                if excluded:
                    self.decide({"action": "nearest", "project_ids": self.ids(excluded),
                                 "cluster": c.cluster, "excluded": True})
                    c.indices = [i for i in c.indices if i not in set(excluded)]
                    if not c.indices:
                        return "done"
            elif action == "nearest":
                self.decide({**base, "action": "nearest"})
                return "done"
            elif action == "unlabelled":
                self.decide({**base, "action": "unlabelled", "alias": True})
                return "done"
            elif action == "remap":
                path = self.choose_existing(c.similar_topics)
                if path is not None:
                    self.decide({**base, "action": "remap", "path": list(path)})
                    return "done"
            elif action == "accept":
                result = self.ask_name(c)
                if result is None:
                    continue
                if result[0] == "remap":
                    self.decide({**base, "action": "remap", "path": list(result[1])})
                    return "done"
                path = self.choose_path(c, result[1])
                if path is not None:
                    self.decide({**base, "action": "accept", "name": result[1], "path": list(path)})
                    return "done"

    def review_isolated(self):
        covered = self.store.covered()
        idx = [i for i in isolated_indices(self.ctx) if int(self.ctx.project_ids[i]) not in covered]
        if not idx:
            return
        choice = self.p.select(f"{len(idx)} progetti isolati (fuori da ogni cluster). Cosa vuoi fare?",
                               [("Tieni a tutti il topic più vicino", "nearest"),
                                ("Rivedili uno per uno", "one")])
        if choice == "nearest":
            self.decide({"action": "nearest", "project_ids": self.ids(idx), "isolated": True})
            return
        for i in idx:
            self.show_projects([i])
            base = {"project_ids": self.ids([i]), "isolated": True}
            action = self.p.select("Topic per questo progetto:", [
                (f"Tieni il più vicino: {fmt_path(self.nearest_path(i))}", "nearest"),
                ("Rimappa su un altro topic", "remap"),
                ("Unlabelled", "unlabelled"),
            ])
            if action == "remap":
                path = self.choose_existing(similar_topics(self.ctx.model, self.hier, self.ctx.embeddings[i]))
                if path is not None:
                    self.decide({**base, "action": "remap", "path": list(path)})
                    continue
                action = "nearest"
            if action == "unlabelled":
                self.decide({**base, "action": "unlabelled", "alias": False})
            else:
                self.decide({**base, "action": "nearest"})

    def run(self):
        clusters = summarize_clusters(self.ctx)
        total = len(clusters)
        numbers = {c.cluster: n for n, c in enumerate(clusters, 1)}
        queue, postponed = list(clusters), set()
        while queue:
            c = queue.pop(0)
            covered = self.store.covered()
            c.indices = [i for i in c.indices if int(self.ctx.project_ids[i]) not in covered]
            if not c.indices:
                continue
            if self.review_cluster(c, numbers[c.cluster], total, allow_later=c.cluster not in postponed) == "later":
                postponed.add(c.cluster)
                queue.append(c)
        self.review_isolated()
        self.review_existing()
        self.show_summary()
        if not self.p.confirm("Applicare queste decisioni (modello, gerarchia e topic dei progetti)?", default=True):
            raise ReviewAborted(f"Review cancelled: nothing was written. Decisions are kept in {self.store.path}")
        return self.store


def run_review(ctx, decisions_path, prompter=None, console=None):
    console = console or Console()
    prompter = prompter or QuestionaryPrompter()
    batch = batch_key(ctx.project_ids)
    store = DecisionStore(decisions_path, batch)
    if decisions_path and os.path.exists(decisions_path):
        previous = DecisionStore.load(decisions_path)
        if previous.batch == batch and previous.decisions and prompter.confirm(
                f"Trovate {len(previous.decisions)} decisioni salvate per questo batch. Riprendere da lì?",
                default=True):
            store = previous
    store.save()

    n_clusters = ctx.report.loc[ctx.report["cluster"] >= 0, "cluster"].nunique()
    console.print(Panel(
        f"{len(ctx.report)} progetti sono poco simili ai topic esistenti: "
        f"{n_clusters} cluster e {(ctx.report['cluster'] < 0).sum()} progetti isolati.\n"
        f"Le decisioni vengono salvate in {decisions_path} man mano.",
        title="Revisione dei possibili topic nuovi", expand=False))
    return Reviewer(ctx, store, prompter, console).run()
