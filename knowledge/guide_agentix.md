# Guide Agentix — Référence d'utilisation

## Qu'est-ce qu'Agentix ?

Agentix est une plateforme d'IA agentique locale. Elle permet de créer des agents IA avec des personnalités, des tools et des budgets de contexte configurables. Les agents peuvent converser, utiliser des outils, accéder à une base de connaissances partagée, déléguer des tâches à d'autres agents, ou débattre entre eux.

## Démarrage

Pour lancer Agentix, exécuter `uv run main.py` dans le dossier du projet, puis ouvrir http://localhost:8000. Toutes les dépendances sont installées automatiquement par uv au premier lancement.

## Configurer un provider LLM

Un provider est un service LLM accessible via une API compatible OpenAI. Pour en ajouter un, cliquer sur l'icône Providers en haut à droite de l'interface, puis remplir l'ID, le label, l'endpoint et éventuellement la clé API. LM Studio utilise l'endpoint http://localhost:1234/v1 sans clé. Ollama utilise http://localhost:11434/v1. OpenAI utilise https://api.openai.com/v1 avec une clé sk-... Le fichier providers.json est créé automatiquement par l'interface.

## Créer un agent

Pour créer un nouvel agent, cliquer sur le bouton Nouvel agent dans la colonne de gauche, saisir un nom, puis ouvrir l'éditeur avec l'icône crayon. L'éditeur contient trois onglets : Prompt pour définir le comportement, Config pour les paramètres techniques, et Contexte pour les budgets de tokens. Les changements sont appliqués immédiatement après sauvegarde.

## Modifier un agent existant

Cliquer sur l'icône crayon à côté du nom de l'agent pour ouvrir l'éditeur. Dans l'onglet Prompt, modifier le texte en Markdown qui décrit le rôle, la personnalité, les objectifs et les contraintes de l'agent. Dans l'onglet Config, choisir le provider et le modèle, ajuster la température et le nombre de tokens max. Les tools s'activent et se désactivent en cliquant sur les badges dans la section Tools. Pour activer la participation au Salon ou au Battle Royale, cocher les cases correspondantes dans l'onglet Config.

## Les tools

Les tools sont les capacités d'action d'un agent. Chaque agent ne voit que les tools qui lui sont explicitement activés. read_file et write_file permettent de lire et écrire dans le workspace privé de l'agent. list_directory liste les fichiers du workspace. search_knowledge permet une recherche sémantique dans la base de connaissances partagée. write_knowledge archive un document dans la base de connaissances. spawn_agent délègue une tâche à un sous-agent. ssh_exec exécute une commande sur un serveur distant. ssh_read_file lit un fichier distant. process_status vérifie si un processus est actif. process_wait attend la fin d'un processus distant.

## La base de connaissances partagée et le RAG

La base de connaissances est un dossier nommé knowledge à la racine du projet. Tous les agents partagent cette base. Pour l'alimenter, déposer des fichiers .txt, .md ou .rst dans ce dossier, puis cliquer sur le bouton Indexer la KB dans l'interface. L'indexation découpe les documents en fragments de 300 mots, génère des embeddings vectoriels et les stocke dans ChromaDB.

À chaque message d'un utilisateur, Agentix recherche automatiquement les fragments les plus pertinents et les injecte dans le contexte de l'agent, dans la limite du budget rag configuré. Ce mécanisme fonctionne même sans activer le tool search_knowledge. Il suffit d'allouer un budget rag supérieur à zéro dans l'onglet Contexte de l'éditeur.

Le tool search_knowledge permet en plus à l'agent de lancer lui-même des recherches pendant son raisonnement, pour interroger la base sur des points précis. Le tool write_knowledge permet à un agent d'archiver automatiquement des informations dans la base, sans intervention manuelle.

Un document ajouté par un agent via write_knowledge est immédiatement indexé et accessible à tous les autres agents. C'est la mémoire collective du système.

## Le workspace privé des agents

Chaque agent dispose d'un dossier memory dans son répertoire. Avec les tools write_file et read_file, un agent peut y stocker des notes, résumés ou résultats entre les sessions. Ces fichiers ne sont pas partagés entre agents et ne sont pas versionnés dans git.

## Les modes de l'interface

Le mode Chat est l'interface principale. Un seul agent, une conversation avec historique persistant. Le panneau de droite affiche les logs en temps réel, la jauge de tokens et les tools actifs.

Le mode Salon est un débat structuré. Plusieurs agents prennent la parole à tour de rôle sur un sujet donné. Chaque agent lit l'historique complet du débat, tronqué à son propre budget d'historique. Un vote final optionnel permet à chaque agent de voter Pour ou Contre la proposition après le dernier tour. Pour qu'un agent apparaisse dans la liste du Salon, activer le flag Peut participer au Salon dans l'onglet Config de l'éditeur.

Le mode Battle Royale est un mode éliminatoire. Les agents se présentent, argumentent pour leur survie, puis votent pour éliminer un adversaire à chaque round. En cas d'égalité des votes, l'élimination est aléatoire. Lors du duel final à deux survivants, un mécanisme de dilemme du prisonnier s'active : voter pour l'adversaire signifie tenter une victoire solo, voter pour soi-même propose un match nul. Si les deux votent pour eux-mêmes, ils survivent ensemble. Pour qu'un agent apparaisse dans la liste du Battle Royale, activer le flag Peut participer au Battle Royale dans l'onglet Config.

## La délégation multi-agents

Un agent peut déléguer une tâche à un sous-agent via le tool spawn_agent. Pour activer cette capacité, ouvrir l'éditeur de l'agent parent, onglet Config, activer le tool spawn_agent et cocher Peut spawner. Dans la section Agents autorisés, sélectionner les agents que cet agent est autorisé à appeler. Si la liste est vide, il peut appeler n'importe quel agent.

Le sous-agent reçoit une tâche et un contexte, s'exécute avec un historique vide, et retourne un résultat au parent. Les deux agents peuvent utiliser des modèles et des providers différents.

## Gestion du contexte et budgets de tokens

Chaque agent a un budget de tokens divisé en compartiments : system pour le prompt système, history pour les messages précédents, rag pour les chunks de la base de connaissances, tools pour les descriptions des tools, et user pour le message de l'utilisateur. La somme des compartiments ne doit pas dépasser le budget total.

Ces budgets se configurent dans l'onglet Contexte de l'éditeur, ou via les sliders dans l'onglet Tokens du panneau de droite. Un agent conversationnel typique aura un history élevé et un rag à zéro. Un agent RAG aura un rag élevé et un history modéré. Un sous-agent exécuteur aura un history à zéro et un user élevé pour recevoir un plan détaillé de son parent.

## Les agents inclus par défaut

Socrate est un agent philosophe sans tools, idéal pour débuter, tester le Salon ou observer la gestion du contexte conversationnel.

Caesar est un planificateur SSH qui interroge l'utilisateur, planifie les commandes à exécuter, puis délègue l'exécution à Centurion. Il nécessite un modèle performant.

Centurion est l'exécuteur SSH qui reçoit les instructions de Caesar et les exécute sur un serveur distant. Il est conçu pour un modèle léger et local. L'authentification SSH par clé publique doit être configurée sur la machine cible avec ssh-copy-id.

## Les templates

Le dossier templates contient quatre exemples non chargés par l'application. assistant_simple est le cas minimal sans tools. agent_rag montre comment utiliser la base de connaissances. planificateur illustre la délégation multi-agents. executeur_ssh montre les tools d'administration distante. Pour utiliser un template, copier son dossier dans agents et l'ouvrir dans l'éditeur.

## Structure des fichiers d'un agent

Chaque agent est un dossier dans agents contenant un fichier agent.md qui décrit le comportement en Markdown avec des sections Nom, Role, Personnalité, Objectif, Capacités et Contraintes, et un fichier config.json qui contient les paramètres techniques. L'éditeur UI modifie ces fichiers directement. Un dossier memory sert de workspace privé persistant.
