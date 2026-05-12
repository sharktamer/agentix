"""
tools.py
========
Les tools sont les capacités d'action d'un agent.

IMPORTANT PÉDAGOGIQUE :
Les étudiants ne modifient PAS ce fichier.
Ils voient les tools disponibles dans l'interface et observent leur exécution.

Nouveauté : chaque agent a sa propre liste de tools autorisés (allowed_tools).
Le tool spawn_agent permet à un agent parent de déléguer une tâche à un
sous-agent existant, avec son propre contexte isolé.
"""

from pathlib import Path

try:
    import paramiko as _paramiko
    _PARAMIKO = True
except ImportError:
    _PARAMIKO = False

WORKSPACE_BASE  = Path(__file__).parent.parent.parent / "agents"
KNOWLEDGE_BASE  = Path(__file__).parent.parent.parent / "knowledge"

# ─── Schémas de tous les tools disponibles ───────────────────────────────────
ALL_TOOLS_SCHEMA = {
    "read_file": {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lit le contenu d'un fichier dans le workspace de l'agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Nom du fichier à lire (ex: notes.txt)"}
                },
                "required": ["filename"]
            }
        }
    },
    "write_file": {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Écrit du contenu dans un fichier dans le workspace de l'agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Nom du fichier"},
                    "content":  {"type": "string", "description": "Contenu à écrire"}
                },
                "required": ["filename", "content"]
            }
        }
    },
    "list_directory": {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "Liste les fichiers dans le workspace de l'agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Sous-dossier à lister (optionnel, '.' par défaut)"}
                },
                "required": []
            }
        }
    },
    "search_knowledge": {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Recherche dans la base de connaissances de l'agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Question ou termes de recherche"}
                },
                "required": ["query"]
            }
        }
    },
    "write_knowledge": {
        "type": "function",
        "function": {
            "name": "write_knowledge",
            "description": (
                "Écrit un document dans la base de connaissances partagée (knowledge/). "
                "Tous les agents peuvent ensuite le retrouver via search_knowledge. "
                "Utilise ce tool pour persister des informations importantes dans la mémoire collective."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Nom du fichier à créer dans knowledge/ (ex: 2026-05-08_sujet.md). Sous-dossiers autorisés."
                    },
                    "content": {
                        "type": "string",
                        "description": "Contenu du document à archiver."
                    }
                },
                "required": ["filename", "content"]
            }
        }
    },
    "spawn_agent": {
        "type": "function",
        "function": {
            "name": "spawn_agent",
            "description": (
                "Délègue une tâche précise à un sous-agent existant. "
                "Le sous-agent exécute sa tâche avec un contexte isolé et retourne un résultat structuré. "
                "Utilise ceci pour décomposer un problème complexe en sous-tâches spécialisées."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Nom du sous-agent à utiliser (doit exister dans le dossier agents/)"
                    },
                    "task": {
                        "type": "string",
                        "description": "Description précise et complète de la tâche à accomplir"
                    },
                    "context": {
                        "type": "string",
                        "description": "Contexte supplémentaire nécessaire au sous-agent (fichiers, données, résumé)"
                    }
                },
                "required": ["agent_name", "task"]
            }
        }
    },
    "ssh_exec": {
        "type": "function",
        "function": {
            "name": "ssh_exec",
            "description": "Exécute une commande shell sur un hôte distant via SSH (clé publique requise dans ~/.ssh/).",
            "parameters": {
                "type": "object",
                "properties": {
                    "host":    {"type": "string",  "description": "Adresse IP ou hostname du serveur distant"},
                    "user":    {"type": "string",  "description": "Nom d'utilisateur SSH"},
                    "command": {"type": "string",  "description": "Commande shell à exécuter"},
                    "port":    {"type": "integer", "description": "Port SSH (22 par défaut)"},
                    "timeout": {"type": "integer", "description": "Timeout en secondes (30 par défaut, jusqu'à 600 pour les opérations longues comme les installations)"},
                },
                "required": ["host", "user", "command"]
            }
        }
    },
    "ssh_read_file": {
        "type": "function",
        "function": {
            "name": "ssh_read_file",
            "description": "Lit le contenu d'un fichier texte sur un hôte distant via SSH.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Adresse IP ou hostname du serveur distant"},
                    "user": {"type": "string", "description": "Nom d'utilisateur SSH"},
                    "path": {"type": "string", "description": "Chemin absolu du fichier à lire"},
                    "port": {"type": "integer", "description": "Port SSH (22 par défaut)"},
                },
                "required": ["host", "user", "path"]
            }
        }
    },
    "process_status": {
        "type": "function",
        "function": {
            "name": "process_status",
            "description": "Vérifie si un processus est en cours d'exécution sur un hôte distant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host":         {"type": "string",  "description": "Adresse IP ou hostname du serveur distant"},
                    "user":         {"type": "string",  "description": "Nom d'utilisateur SSH"},
                    "process_name": {"type": "string",  "description": "Nom du processus à vérifier (ex: nginx, python3)"},
                    "port":         {"type": "integer", "description": "Port SSH (22 par défaut)"},
                },
                "required": ["host", "user", "process_name"]
            }
        }
    },
    "process_wait": {
        "type": "function",
        "function": {
            "name": "process_wait",
            "description": "Attend qu'un processus se termine sur un hôte distant (polling toutes les 2s). Bloquant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host":         {"type": "string",  "description": "Adresse IP ou hostname du serveur distant"},
                    "user":         {"type": "string",  "description": "Nom d'utilisateur SSH"},
                    "process_name": {"type": "string",  "description": "Nom du processus à attendre"},
                    "timeout":      {"type": "integer", "description": "Timeout en secondes (60 par défaut)"},
                    "port":         {"type": "integer", "description": "Port SSH (22 par défaut)"},
                },
                "required": ["host", "user", "process_name"]
            }
        }
    },
}


def get_tools_schema_for_agent(allowed_tools: list) -> list:
    """
    Retourne uniquement les schémas des tools autorisés pour un agent.
    C'est la clé de la restriction par agent.
    """
    return [ALL_TOOLS_SCHEMA[name] for name in allowed_tools if name in ALL_TOOLS_SCHEMA]


def get_tools_description_for_agent(allowed_tools: list) -> str:
    """Génère une description textuelle des tools autorisés (pour le context manager)."""
    lines = ["Outils disponibles (function calling) :"]
    descriptions = {
        "read_file":        "read_file(filename) : lire un fichier du workspace privé",
        "write_file":       "write_file(filename, content) : écrire dans le workspace privé",
        "list_directory":   "list_directory(path?) : lister les fichiers du workspace privé",
        "search_knowledge": "search_knowledge(query) : recherche sémantique dans la KB partagée",
        "write_knowledge":  "write_knowledge(filename, content) : archiver un document dans la KB partagée (knowledge/)",
        "spawn_agent":      "spawn_agent(agent_name, task, context?) : déléguer une tâche à un sous-agent",
        "ssh_exec":         "ssh_exec(host, user, command, port?) : exécuter une commande sur un serveur distant",
        "ssh_read_file":    "ssh_read_file(host, user, path, port?) : lire un fichier sur un serveur distant",
        "process_status":   "process_status(host, user, process_name, port?) : vérifier si un processus tourne",
        "process_wait":     "process_wait(host, user, process_name, timeout?, port?) : attendre la fin d'un processus",
    }
    for name in allowed_tools:
        if name in descriptions:
            lines.append(f"- {descriptions[name]}")
    return "\n".join(lines)


def execute_tool(tool_name: str, parameters: dict, agent_name: str, rag_engine=None) -> dict:
    """
    Exécute un tool et retourne le résultat.
    spawn_agent est géré séparément par l'orchestrateur (nécessite async).
    """
    agent_workspace = WORKSPACE_BASE / agent_name

    try:
        if tool_name == "read_file":
            return _read_file(parameters.get("filename", ""), agent_workspace)
        elif tool_name == "write_file":
            return _write_file(parameters.get("filename", ""), parameters.get("content", ""), agent_workspace)
        elif tool_name == "list_directory":
            return _list_directory(parameters.get("path", "."), agent_workspace)
        elif tool_name == "search_knowledge":
            return _search_knowledge(parameters.get("query", ""), rag_engine)
        elif tool_name == "write_knowledge":
            return _write_knowledge(parameters.get("filename", ""), parameters.get("content", ""), rag_engine)
        elif tool_name == "spawn_agent":
            return {"success": True, "result": "__SPAWN_AGENT__", "_spawn": True}
        elif tool_name == "ssh_exec":
            return _ssh_exec(
                parameters.get("host", ""), parameters.get("user", ""),
                parameters.get("command", ""), int(parameters.get("port", 22)),
                int(parameters.get("timeout", 30)),
            )
        elif tool_name == "ssh_read_file":
            return _ssh_read_file(
                parameters.get("host", ""), parameters.get("user", ""),
                parameters.get("path", ""), int(parameters.get("port", 22))
            )
        elif tool_name == "process_status":
            return _process_status(
                parameters.get("host", ""), parameters.get("user", ""),
                parameters.get("process_name", ""), int(parameters.get("port", 22))
            )
        elif tool_name == "process_wait":
            return _process_wait(
                parameters.get("host", ""), parameters.get("user", ""),
                parameters.get("process_name", ""),
                int(parameters.get("timeout", 60)), int(parameters.get("port", 22))
            )
        else:
            return {"success": False, "error": f"Tool inconnu : {tool_name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _write_knowledge(filename: str, content: str, rag_engine=None) -> dict:
    if not filename.strip():
        return {"success": False, "error": "Nom de fichier vide."}
    target = (KNOWLEDGE_BASE / filename).resolve()
    if not str(target).startswith(str(KNOWLEDGE_BASE.resolve())):
        return {"success": False, "error": "Accès refusé : chemin hors de knowledge/."}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    if rag_engine:
        stats = rag_engine.index_file(target)
        return {"success": True, "result": f"Document '{filename}' archivé et indexé ({stats['chunks']} chunk(s) dans la KB partagée)."}

    return {"success": True, "result": f"Document '{filename}' archivé dans la KB partagée ({len(content)} caractères)."}


def _search_knowledge(query: str, rag_engine) -> dict:
    if not rag_engine:
        return {"success": False, "error": "RAG engine non initialisé."}
    if not query.strip():
        return {"success": False, "error": "Query vide."}
    chunks = rag_engine.search(query)
    if not chunks:
        return {"success": True, "result": "Aucun document pertinent trouvé dans la base de connaissances."}
    lines = []
    for i, c in enumerate(chunks, 1):
        lines.append(f"[Extrait {i} — {c['source']}, pertinence: {c['relevance']}]\n{c['text']}")
    return {"success": True, "result": "\n\n---\n\n".join(lines)}


def _read_file(filename, workspace):
    target = (workspace / filename).resolve()
    if not str(target).startswith(str(workspace.resolve())):
        return {"success": False, "error": "Accès refusé : hors du workspace"}
    if not target.exists():
        return {"success": False, "error": f"Fichier non trouvé : {filename}"}
    content = target.read_text(encoding="utf-8")
    return {"success": True, "result": content[:2000]}


def _write_file(filename, content, workspace):
    target = (workspace / filename).resolve()
    if not str(target).startswith(str(workspace.resolve())):
        return {"success": False, "error": "Accès refusé : hors du workspace"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"success": True, "result": f"Fichier {filename} écrit ({len(content)} caractères)"}


def _list_directory(path, workspace):
    target = (workspace / path).resolve()
    if not str(target).startswith(str(workspace.resolve())):
        return {"success": False, "error": "Accès refusé : hors du workspace"}
    if not target.is_dir():
        return {"success": False, "error": f"Dossier non trouvé : {path}"}
    entries = []
    for item in sorted(target.iterdir()):
        kind = "📁" if item.is_dir() else "📄"
        entries.append(f"{kind} {item.name}")
    return {"success": True, "result": "\n".join(entries) or "(dossier vide)"}


# ─── SSH helpers ──────────────────────────────────────────────────────────────

def _ssh_connect(host: str, user: str, port: int):
    """Ouvre une connexion SSH via clé publique (~/.ssh/). Lève une exception en cas d'échec."""
    if not _PARAMIKO:
        raise RuntimeError("paramiko non installé — lancer : uv pip install paramiko")
    client = _paramiko.SSHClient()
    # AutoAddPolicy accepte automatiquement les clés inconnues (contexte pédagogique)
    client.set_missing_host_key_policy(_paramiko.AutoAddPolicy())
    client.connect(hostname=host, port=port, username=user, timeout=10)
    return client


def _ssh_exec(host: str, user: str, command: str, port: int = 22, timeout: int = 30) -> dict:
    if not host or not user or not command:
        return {"success": False, "error": "host, user et command sont requis."}
    timeout = max(5, min(timeout, 600))  # borné entre 5s et 600s
    try:
        client = _ssh_connect(host, user, port)
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        client.close()
        if err and not out:
            return {"success": False, "error": err[:1000]}
        result = out[:2000]
        if err:
            result += f"\n[stderr]: {err[:300]}"
        return {"success": True, "result": result or "(aucune sortie)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _ssh_read_file(host: str, user: str, path: str, port: int = 22) -> dict:
    if not host or not user or not path:
        return {"success": False, "error": "host, user et path sont requis."}
    try:
        client = _ssh_connect(host, user, port)
        sftp = client.open_sftp()
        with sftp.open(path, "r") as f:
            content = f.read().decode("utf-8", errors="replace")
        sftp.close()
        client.close()
        return {"success": True, "result": content[:3000]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _process_status(host: str, user: str, process_name: str, port: int = 22) -> dict:
    if not host or not user or not process_name:
        return {"success": False, "error": "host, user et process_name sont requis."}
    result = _ssh_exec(host, user, f"pgrep -x {process_name}", port)
    if not result["success"]:
        return result
    pids    = result["result"].strip()
    running = bool(pids)
    label   = f"en cours (PID: {pids})" if running else "non trouvé (arrêté)"
    return {"success": True, "result": f"Processus '{process_name}' : {label}", "running": running}


def _process_wait(host: str, user: str, process_name: str, timeout: int = 60, port: int = 22) -> dict:
    import time
    if not host or not user or not process_name:
        return {"success": False, "error": "host, user et process_name sont requis."}
    start = time.time()
    while time.time() - start < timeout:
        status = _process_status(host, user, process_name, port)
        if not status["success"]:
            return status
        if not status.get("running", True):
            elapsed = round(time.time() - start, 1)
            return {"success": True, "result": f"Processus '{process_name}' terminé après {elapsed}s."}
        time.sleep(2)
    return {"success": False, "error": f"Timeout : '{process_name}' toujours actif après {timeout}s."}
