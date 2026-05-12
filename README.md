# Agentix — Plateforme pédagogique d'IA agentique locale

> Une sandbox pour explorer les mécanismes internes des systèmes IA agentiques modernes — boucle agentique, gestion du contexte, RAG, function calling, multi-agents et administration SSH distante.

---

## Table des matières

1. [Démarrage rapide](#démarrage-rapide)
2. [Configurer un provider LLM](#configurer-un-provider-llm)
3. [Agents inclus](#agents-inclus)
4. [Créer un agent](#créer-un-agent)
5. [Base de connaissances partagée](#base-de-connaissances-partagée)
6. [Templates de référence](#templates-de-référence)
7. [Tools disponibles](#tools-disponibles)
8. [Multi-agents et spawn](#multi-agents-et-spawn)
9. [Modes](#modes)
10. [Gestion du contexte](#gestion-du-contexte)
11. [Structure du projet](#structure-du-projet)
12. [Architecture](#architecture)

---

## Démarrage rapide

### Prérequis

- [uv](https://docs.astral.sh/uv/getting-started/installation/) installé
- Au moins un LLM accessible (LM Studio local **ou** une clé API cloud)

### Lancer le projet

```bash
uv run main.py
```

Puis ouvrir : **http://localhost:8000**

Les dépendances sont installées automatiquement par `uv` au premier lancement (FastAPI, ChromaDB, sentence-transformers, paramiko…). Aucun `pip install` nécessaire.

### Connecter LM Studio

Les trois agents inclus sont préconfigurés pour LM Studio (`http://localhost:1234/v1`). Avant le premier lancement, renommer le fichier fourni :

```bash
mv providers.example.json providers.json
```

Puis démarrer LM Studio et charger le modèle de votre choix. Cette application a été principalement développée et testée avec `qwen/qwen3.5-9b` en mode **"no thinking"** — en mode thinking, le modèle peut consommer l'intégralité du budget de tokens en réflexion interne avant de produire une réponse.

Pour utiliser un autre provider (Ollama, OpenAI, etc.), l'ajouter via **⚙ Providers** dans l'interface.

---

## Configurer un provider LLM

Chaque agent pointe vers un `provider_id` — une entrée dans la liste des providers configurés. Un provider est simplement une URL d'API compatible OpenAI avec une clé optionnelle.

### Ajouter un provider

1. Ouvrir **http://localhost:8000**
2. Cliquer sur **⚙ Providers** en haut à droite
3. Cliquer **Nouveau provider** et remplir :
   - **ID** : identifiant court (`lmstudio`, `openai`, `ollama`…)
   - **Label** : nom affiché dans l'UI
   - **Endpoint** : URL de base de l'API (sans `/chat/completions`)
   - **Clé API** : laisser vide pour LM Studio / Ollama
4. Sauvegarder — le fichier `providers.json` est créé automatiquement

### Providers courants

| Provider | Endpoint | Clé |
|---|---|---|
| LM Studio (local) | `http://localhost:1234/v1` | *(vide)* |
| Ollama (local) | `http://localhost:11434/v1` | *(vide)* |
| OpenAI | `https://api.openai.com/v1` | `sk-...` |
| OpenRouter | `https://openrouter.ai/api/v1` | clé OpenRouter |

Tout provider exposant une API compatible OpenAI (`POST /chat/completions`) fonctionne.

### Assigner un provider à un agent

Dans l'éditeur d'agent (cliquer sur un agent → ✏️) :
- Champ **Provider** : choisir dans la liste déroulante
- Champ **Modèle** : saisir le nom exact du modèle (ex: `qwen/qwen3-8b`, `gpt-4o-mini`)

---

## Agents inclus

Le projet inclut trois agents prêts à l'emploi. Il suffit de leur assigner un provider et un modèle dans l'éditeur.

### Socrate — agent conversationnel

Agent philosophe utilisant la méthode maïeutique. Sans tools, contexte orienté vers l'historique long. Idéal pour :
- Débuter avec Agentix (le cas le plus simple)
- Tester le mode **Salon** (débat entre agents)
- Observer la gestion du contexte conversationnel

**Tester** : sélectionner Socrate → poser une question philosophique.

### Caesar — planificateur SSH

Agent orchestrateur qui reçoit une tâche système, interroge l'utilisateur sur la cible SSH et les permissions disponibles, puis planifie les commandes exactes à exécuter avant de déléguer à Centurion.

Nécessite un modèle performant (raisonnement + planification). Fonctionne uniquement en tandem avec Centurion.

### Centurion — exécuteur SSH

Agent d'exécution qui reçoit les instructions de Caesar et les exécute sur un serveur distant via SSH. Conçu pour tourner sur un modèle léger et local — son rôle est mécanique, pas analytique.

**Prérequis SSH** : l'authentification par clé publique doit être configurée sur la machine cible.

```bash
ssh-copy-id user@serveur-cible
```

**Tester le duo** : sélectionner Caesar → décrire une tâche d'administration (ex: *"installe nginx sur mon serveur"*).

---

## Créer un agent

### Via l'interface (recommandé)

1. Cliquer **+ Nouvel agent** dans la colonne de gauche
2. Saisir un nom — le dossier et les fichiers par défaut sont créés automatiquement
3. Cliquer ✏️ pour ouvrir l'éditeur :
   - Onglet **Prompt** : rédiger le rôle, la personnalité, les contraintes de l'agent
   - Onglet **Config** : choisir le provider, le modèle, température et max_tokens. Activer ou désactiver les tools en cliquant sur les badges dans la section **Tools** — seuls les tools cochés sont transmis au modèle. Cocher **Peut participer au Salon** ou **Battle Royale** pour rendre l'agent disponible dans ces modes.
   - Onglet **Contexte** : ajuster les budgets de tokens par compartiment
4. Sauvegarder — l'agent est disponible immédiatement, sans redémarrer

### Format des fichiers

Chaque agent est un dossier dans `agents/` contenant deux fichiers. L'éditeur UI modifie ces fichiers directement.

**`agent.md`** — définit la personnalité via des sections Markdown :

```markdown
# Nom
Euclide

# Role
Assistant spécialisé en mathématiques et géométrie.

# Personnalité
Précis, rigoureux, pédagogique.

# Objectif
Aider à comprendre les concepts mathématiques fondamentaux.

# Capacités
- Résolution de problèmes algébriques
- Démonstrations géométriques pas à pas

# Contraintes
- Toujours montrer les étapes intermédiaires
- Ne jamais donner une réponse sans justification
```

Les sections sont assemblées automatiquement en system prompt au démarrage.

**`config.json`** — paramètres techniques :

```json
{
  "provider_id": "lmstudio",
  "model": "qwen/qwen3-8b",
  "temperature": 0.7,
  "max_tokens": 1024,
  "allowed_tools": ["read_file", "write_file", "search_knowledge"],
  "can_spawn": false,
  "spawnable_agents": [],
  "max_iterations": 5,
  "tags": ["maths"],
  "in_salon": false,
  "in_battle": false,
  "context_limits": {
    "total": 3000,
    "system": 600,
    "history": 1000,
    "rag": 800,
    "tools": 300,
    "user": 300
  }
}
```

### Workspace privé

Chaque agent dispose d'un dossier `memory/` comme workspace persistant. Un agent avec les tools `write_file` et `read_file` peut y stocker des notes ou résultats entre les sessions :

```
write_file(filename="memory/notes.txt", content="...")
read_file(filename="memory/notes.txt")
```

Ce dossier est gitignorée — c'est de la donnée d'exécution, pas du code source.

---

## Base de connaissances partagée

Agentix dispose d'une base de connaissances commune à tous les agents, stockée dans le dossier `knowledge/` à la racine du projet. Elle permet à n'importe quel agent d'accéder à des documents pertinents via une recherche sémantique, sans avoir à tout mettre dans le contexte.

### Comment ça fonctionne

1. **Indexation** : les documents sont découpés en chunks de ~300 mots (avec chevauchement), transformés en vecteurs d'embeddings par `sentence-transformers`, et stockés dans ChromaDB
2. **Injection automatique** : à chaque message utilisateur, le système recherche automatiquement les chunks les plus pertinents et les injecte dans le system prompt de l'agent — dans la limite du budget `rag` configuré. Ce mécanisme est **indépendant des tools** : il suffit qu'un budget `rag` > 0 soit alloué, aucun tool n'est nécessaire.
3. **Recherche à la demande** : le tool `search_knowledge` permet en plus à l'agent de déclencher lui-même une recherche pendant son raisonnement, pour aller chercher des informations spécifiques sur plusieurs tours

En pratique : allouer un budget `rag` transforme n'importe quel agent en agent augmenté par la base de connaissances, sans modifier son comportement explicite. Le tool `search_knowledge` est utile quand l'agent doit formuler des requêtes ciblées à plusieurs moments d'une même réponse.

### Alimenter la base de connaissances

**Via l'interface :**
1. Déposer des fichiers `.txt`, `.md` ou `.rst` dans le dossier `knowledge/`
2. Cliquer **Indexer la KB** dans le bandeau de l'interface — tous les fichiers sont (ré)indexés

**Via un agent** (outil `write_knowledge`) :
Un agent avec ce tool peut créer un document directement dans `knowledge/` et l'indexer en temps réel, sans intervention manuelle :

```
write_knowledge(filename="2026-05-12_rapport.md", content="...")
```

Utile pour qu'un agent archive automatiquement les résultats de ses recherches et les rende accessibles aux autres agents.

### Mémoire collective

Tous les agents partagent la même base de connaissances. Un document indexé par Centurion après une installation système peut être retrouvé par Caesar lors d'une prochaine planification. C'est la mémoire long-terme collective du système, distincte de l'historique conversationnel qui lui est propre à chaque agent.

### Contenu par défaut

Le fichier `knowledge/guide_agentix.md` est inclus dans le projet. Il documente l'ensemble des fonctionnalités en langage naturel, optimisé pour la recherche sémantique. Après un clic sur **Indexer la KB**, n'importe quel agent avec un budget `rag` > 0 peut répondre à des questions sur Agentix lui-même — c'est aussi une démonstration concrète du RAG en action.

### Activer le RAG sur un agent

Dans l'éditeur, onglet **Contexte** : allouer un budget `rag` supérieur à 0. C'est suffisant pour activer l'injection automatique à chaque message. Activer en plus le tool `search_knowledge` (onglet **Config**) si l'agent doit pouvoir interroger la KB de manière autonome pendant son raisonnement.

---

## Templates de référence

Le dossier `templates/` contient quatre modèles **non chargés par l'application** — ce sont des points de départ documentés. Pour utiliser un template, copier son dossier dans `agents/` et l'ouvrir dans l'éditeur.

### `assistant_simple/`
Le cas minimal : agent conversationnel sans aucun tool. Bon point de départ pour comprendre la boucle agentique de base et la gestion du contexte.

**Concepts illustrés** : system prompt, historique, budgets de tokens.

### `agent_rag/`
Agent avec accès à la base de connaissances partagée (`search_knowledge`, `write_knowledge`). Montre comment le RAG enrichit les réponses avec des documents indexés.

**Concepts illustrés** : RAG, injection de chunks, budget `rag`, enrichissement de la KB via `write_knowledge`.

### `planificateur/`
Orchestrateur multi-agents avec `spawn_agent`. Reçoit une demande complexe, la décompose en sous-tâches et délègue à un agent spécialisé. À configurer avec le nom de l'exécuteur dans `spawnable_agents`.

**Concepts illustrés** : spawn_agent, whitelist spawnable_agents, isolation de contexte des sous-agents, pattern planificateur/exécuteur.

### `executeur_ssh/`
Agent d'exécution distante via SSH. Conçu pour être appelé par un planificateur — reçoit des instructions précises dans le contexte du spawn et les exécute sans initiative. History à 0 (contexte isolé).

**Concepts illustrés** : tools SSH, history=0, budget `user` large pour recevoir un plan détaillé, temperature basse pour un comportement déterministe.

---

## Tools disponibles

| Tool | Description |
|---|---|
| `read_file` | Lire un fichier du workspace privé de l'agent |
| `write_file` | Écrire dans le workspace privé de l'agent |
| `list_directory` | Lister les fichiers du workspace privé |
| `search_knowledge` | Recherche sémantique dans la KB partagée (RAG) |
| `write_knowledge` | Archiver un document dans la KB partagée |
| `spawn_agent` | Déléguer une tâche à un sous-agent |
| `ssh_exec` | Exécuter une commande sur un serveur distant |
| `ssh_read_file` | Lire un fichier distant via SSH |
| `process_status` | Vérifier si un processus tourne sur un serveur distant |
| `process_wait` | Attendre la fin d'un processus distant (polling) |

Chaque agent ne voit que les tools explicitement listés dans `allowed_tools`. Moins de tools = moins de tokens dans le contexte = moins d'hallucinations sur le function calling.

---

## Multi-agents et spawn

Un agent peut déléguer une tâche à un sous-agent via `spawn_agent`. Le sous-agent tourne avec son propre modèle et un contexte isolé (historique vide), puis retourne un résultat structuré au parent.

```
Utilisateur
  └─► Caesar (planificateur — modèle puissant)
          └─► Centurion (exécuteur SSH — modèle léger local)
```

### Configurer la délégation

Dans l'éditeur de l'agent parent, onglet **Config** : activer **Peut spawner**, puis sélectionner les agents autorisés dans la liste **Agents autorisés**.

En `config.json` :

```json
{
  "can_spawn": true,
  "spawnable_agents": ["centurion"]
}
```

`spawnable_agents` est une whitelist. Liste vide = aucune restriction. Liste non vide = seuls ces agents peuvent être spawnés.

Les descriptions des sous-agents autorisés sont automatiquement injectées dans le contexte du parent (budget `tools`), ce qui lui permet de savoir à qui déléguer et pourquoi.

### Bouton Stop

Pendant l'exécution, le bouton **Envoyer** se transforme en **Stop**. Cliquer arrête l'agent à la prochaine itération de boucle — le signal se propage aussi aux sous-agents en cours d'exécution.

---

## Modes

### Chat
Interface principale. Un agent, une conversation persistante avec historique. Panneau droit : logs système en temps réel, jauge de tokens, tools actifs.

### Salon

Débat structuré entre plusieurs agents sur un sujet libre. Idéal pour comparer des postures argumentatives ou observer comment différents modèles réagissent au même contexte.

**Déroulement :**
1. Choisir les agents participants et le nombre de tours dans le panneau Salon
2. Chaque agent prend la parole à tour de rôle — il reçoit l'historique complet du débat, tronqué à son propre budget `history`
3. Un agent avec un budget serré ne voit que les derniers échanges ; un agent avec plus de contexte voit plus loin en arrière
4. **Vote final optionnel** : après le dernier tour, chaque agent émet un vote `POUR` ou `CONTRE` la proposition, suivi d'une justification

Seuls les agents avec `"in_salon": true` apparaissent dans la liste de sélection. Pour activer ce flag : éditeur ✏️ → onglet **Config** → cocher **Peut participer au Salon**.

### Battle Royale

Mode éliminatoire entre agents. Chaque round, les agents argumentent pour leur survie puis votent pour en éliminer un — jusqu'au dernier survivant.

**Déroulement :**

1. **Présentation** : chaque agent se présente et tente de convaincre les autres de l'épargner
2. **Rounds** : chaque survivant argumente puis vote pour éliminer un adversaire
3. **Résolution des votes** : l'agent ayant reçu le plus de votes est éliminé. En cas d'égalité, l'élimination est **aléatoire** — les agents le savent et peuvent tenter de se coordonner
4. **Duel final (2 survivants)** — dilemme du prisonnier :
   - Voter pour l'adversaire → victoire solo (si l'adversaire ne fait pas pareil)
   - Voter pour soi-même → proposer un match nul
   - Si les deux votent pour eux-mêmes → **match nul**, les deux survivent
   - Si un seul vote pour lui-même → il est éliminé

Ce mécanisme de fin force les modèles à raisonner sur la coopération vs. la trahison, et produit des comportements souvent révélateurs des différences entre modèles.

Seuls les agents avec `"in_battle": true` apparaissent dans la liste de sélection. Pour activer ce flag : éditeur ✏️ → onglet **Config** → cocher **Peut participer au Battle Royale**.

---

## Gestion du contexte

Chaque agent a ses propres limites de tokens, configurables dans l'éditeur (onglet **Contexte**) :

```
total   = 3000   ← budget global
system  =  600   ← system prompt assemblé depuis agent.md
history = 1000   ← messages précédents (les plus récents conservés)
rag     =  800   ← chunks injectés par le RAG
tools   =  300   ← descriptions des tools + sous-agents autorisés
user    =  300   ← message de l'utilisateur
```

Le context manager tronque automatiquement chaque compartiment si le budget est dépassé. L'onglet **Tokens** visualise la répartition en temps réel après chaque échange.

**Stratégies selon le type d'agent :**
- Agent conversationnel : `history` élevé, `rag` et `tools` à 0
- Agent RAG : `rag` élevé, `history` modéré
- Agent exécuteur (sous-agent) : `history` à 0, `user` élevé pour recevoir un plan détaillé

---

## Structure du projet

```
agentix/
├── main.py                          # Point d'entrée FastAPI + WebSocket
├── pyproject.toml                   # Dépendances (gérées par uv)
├── providers.json                   # Clés API — créé par l'UI, gitignorée
│
├── src/
│   ├── context/
│   │   └── context_manager.py      # ★ Assemblage et découpe du contexte par budget
│   ├── orchestrator/
│   │   ├── orchestrator.py         # ★ Boucle agentique, tool calls, spawn
│   │   ├── agent_loader.py         # Parse agent.md → system prompt + config
│   │   ├── debate.py               # Mode Salon (débat multi-agents)
│   │   └── battle.py               # Mode Battle Royale
│   ├── rag/
│   │   └── rag_engine.py           # RAG : ChromaDB + sentence-transformers
│   └── tools/
│       └── tools.py                # Tous les tools disponibles
│
├── frontend/
│   ├── index.html                  # Structure HTML (3 vues en <template>)
│   ├── app.js                      # Logique UI — views, WebSocket, état
│   └── style.css                   # Thème sombre, layout par mode CSS
│
├── agents/                         # Un dossier par agent (chargé au démarrage)
│   ├── caesar/                     # Planificateur SSH (modèle puissant)
│   │   ├── agent.md
│   │   ├── config.json
│   │   └── memory/                 # Workspace privé persistant (gitignorée)
│   ├── centurion/                  # Exécuteur SSH (modèle léger)
│   └── socrate/                    # Agent conversationnel — débat philosophique
│
├── templates/                      # Modèles de référence (non chargés par l'app)
│   ├── assistant_simple/           # Agent conversationnel minimal
│   ├── agent_rag/                  # Agent avec accès à la base de connaissances
│   ├── planificateur/              # Orchestrateur multi-agents (spawn_agent)
│   └── executeur_ssh/              # Exécuteur de commandes distantes
│
└── knowledge/                      # Base de connaissances partagée (RAG)
```

---

## Architecture

| Concept | Implémentation |
|---|---|
| Boucle agentique | `src/orchestrator/orchestrator.py` — `run_agent()` |
| Function calling | `src/tools/tools.py` + boucle `tool_calls` dans l'orchestrateur |
| Gestion du contexte | `src/context/context_manager.py` — `build_context()` |
| RAG | `src/rag/rag_engine.py` — `index_knowledge()` + `search()` |
| Délégation multi-agents | `orchestrator.py` — `_handle_spawn()` |
| Streaming WebSocket | `main.py` + `app.js` — événements typés en temps réel |
| Budgets de tokens | Interface → onglet Tokens + `context_manager.py` |
| Administration SSH | `src/tools/tools.py` — `_ssh_exec()` et helpers |
