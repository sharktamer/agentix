# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastapi>=0.111.0",
#     "uvicorn[standard]>=0.29.0",
#     "websockets>=12.0",
#     "httpx>=0.27.0",
#     "tiktoken>=0.7.0",
#     "pydantic>=2.7.0",
#     "python-multipart>=0.0.9",
#     "paramiko>=3.0.0",
#     "chromadb>=0.5.0",
#     "sentence-transformers>=3.0.0",
# ]
# ///
"""
main.py — Agentix v4
====================
Démarrage : uv run main.py
RAG       : uv run --with chromadb --with sentence-transformers main.py

Changements v4 :
    - Knowledge base partagée : knowledge/ à la racine, une seule instance RAGEngine
    - Contexte par agent : chaque agent a ses propres limites dans config.json
    - POST /knowledge/index      → indexer la KB partagée
    - GET  /knowledge/status     → statut de la KB partagée
    - PUT  /agents/{name}/context-limits → modifier les limites d'un agent (validées)
    - Suppression des endpoints globaux /context-limits
"""

import json
import sys
import asyncio
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from uuid import uuid4

from orchestrator.agent_loader import (
    ALL_TOOLS, discover_agents, load_agent,
    save_agent_markdown, save_agent_config, create_agent,
)
from orchestrator.orchestrator import run_agent, set_providers, get_provider_endpoint
from orchestrator.debate import run_debate
from orchestrator.battle import run_battle
from rag.rag_engine import RAGEngine
from tools.tools import ALL_TOOLS_SCHEMA

BASE_DIR        = Path(__file__).parent
AGENTS_DIR      = BASE_DIR / "agents"
FRONTEND_DIR    = BASE_DIR / "frontend"
KNOWLEDGE_DIR   = BASE_DIR / "knowledge"
PROVIDERS_FILE  = BASE_DIR / "providers.json"

app = FastAPI(title="Agentix", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── État global ──────────────────────────────────────────────────────────────
_agents:      dict       = {}
_websockets:  dict       = {}
_shared_rag:  RAGEngine  = None

# Sessions persistantes par agent (agent_name → {history, messages})
_agent_sessions: dict = {}

# Débats / battles en cours (id → True si annulé)
_debate_cancelled: dict = {}
_battle_cancelled: dict = {}

# Flags d'arrêt par agent (agent_name → {"cancelled": bool})
_agent_stop_flags: dict = {}


# ─── Démarrage ────────────────────────────────────────────────────────────────
def _load_providers() -> dict:
    if PROVIDERS_FILE.exists():
        try:
            return json.loads(PROVIDERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_providers(providers: dict):
    PROVIDERS_FILE.write_text(json.dumps(providers, indent=2, ensure_ascii=False), encoding="utf-8")


@app.on_event("startup")
async def startup():
    global _shared_rag
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    _shared_rag = RAGEngine("shared", KNOWLEDGE_DIR)
    _reload_all_agents()
    providers = _load_providers()
    set_providers(providers)
    rag_info = _shared_rag.get_status()
    print(f"✅ Agentix v4 — {len(_agents)} agent(s)")
    print(f"🔌 {len(providers)} provider(s) chargé(s)")
    print(f"📚 KB partagée : {rag_info['count']} chunk(s) indexés (knowledge/)")
    print(f"🌐 http://localhost:8000")


# ─── Knowledge base partagée ──────────────────────────────────────────────────

@app.get("/knowledge/status")
async def get_knowledge_status():
    """Statut de la KB partagée."""
    if not _shared_rag:
        return {"available": False, "count": 0}
    return _shared_rag.get_status()


@app.post("/knowledge/index")
async def index_shared_knowledge():
    """Indexe tous les fichiers du dossier knowledge/ partagé."""
    if not _shared_rag or not _shared_rag.available:
        return {"error": "RAG non disponible (lancer avec --with chromadb --with sentence-transformers)"}
    stats = _shared_rag.index_knowledge()
    return {"status": "ok", "stats": stats}


# ─── Agents : lecture ─────────────────────────────────────────────────────────

@app.get("/agents")
async def list_agents():
    shared_rag_status = _shared_rag.get_status() if _shared_rag else {"available": False, "count": 0}
    result = []
    for name, agent in _agents.items():
        session = _agent_sessions.get(name, {})
        result.append({
            "name":             agent.name,
            "role":             agent.metadata.get("role", ""),
            "model":            agent.config.model,
            "provider_id":      agent.config.provider_id,
            "allowed_tools":    agent.config.allowed_tools,
            "can_spawn":        agent.config.can_spawn,
            "spawnable_agents": agent.config.spawnable_agents,
            "max_iterations":   agent.config.max_iterations,
            "context_limits":   agent.config.limits.to_dict(),
            "tags":             agent.config.tags,
            "in_salon":         agent.config.in_salon,
            "in_battle":        agent.config.in_battle,
            "message_count":    len(session.get("messages", [])),
        })
    return {"agents": result, "shared_rag": shared_rag_status}


@app.get("/agents/{agent_name}")
async def get_agent(agent_name: str):
    agent = _agents.get(agent_name)
    if not agent:
        return {"error": f"Agent '{agent_name}' non trouvé"}
    config_dict = {
        "provider_id":      agent.config.provider_id,
        "model":            agent.config.model,
        "temperature":      agent.config.temperature,
        "max_tokens":       agent.config.max_tokens,
        "allowed_tools":    agent.config.allowed_tools,
        "can_spawn":        agent.config.can_spawn,
        "spawnable_agents": agent.config.spawnable_agents,
        "max_iterations":   agent.config.max_iterations,
        "limits":           agent.config.limits.to_dict(),
        "tags":             agent.config.tags,
        "in_salon":         agent.config.in_salon,
        "in_battle":        agent.config.in_battle,
    }
    return {
        "name":         agent.name,
        "metadata":     agent.metadata,
        "system_prompt": agent.system_prompt,
        "config":        config_dict,
        "raw_markdown":  agent.raw_markdown,
        "shared_rag":    _shared_rag.get_status() if _shared_rag else {"available": False, "count": 0},
    }


@app.get("/agents/{agent_name}/session")
async def get_agent_session(agent_name: str):
    session = _agent_sessions.get(agent_name, {"history": [], "messages": []})
    return {
        "agent_name": agent_name,
        "messages":   session.get("messages", []),
        "history":    session.get("history",  []),
    }


@app.delete("/agents/{agent_name}/session")
async def clear_agent_session(agent_name: str):
    _agent_sessions[agent_name] = {"history": [], "messages": []}
    return {"status": "cleared"}


@app.post("/agents/{agent_name}/stop")
async def stop_agent(agent_name: str):
    flag = _agent_stop_flags.get(agent_name)
    if flag:
        flag["cancelled"] = True
        return {"status": "stopping"}
    return {"status": "not_running"}


# ─── Agents : création / édition / suppression ────────────────────────────────

class CreateAgentBody(BaseModel):
    name: str

@app.post("/agents")
async def create_new_agent(body: CreateAgentBody):
    name = body.name.strip().lower().replace(" ", "_")
    if not name:        return {"error": "Nom invalide"}
    if name in _agents: return {"error": f"Agent '{name}' existe déjà"}
    agent_path = create_agent(AGENTS_DIR, name)
    agent = load_agent(agent_path)
    if agent:
        _agents[name] = agent
    return {"status": "created", "name": name}


class SaveMarkdownBody(BaseModel):
    content: str

@app.put("/agents/{agent_name}/markdown")
async def save_markdown(agent_name: str, body: SaveMarkdownBody):
    agent = _agents.get(agent_name)
    if not agent: return {"error": f"Agent '{agent_name}' non trouvé"}
    save_agent_markdown(agent.path, body.content)
    reloaded = load_agent(agent.path)
    if reloaded: _agents[agent_name] = reloaded
    return {"status": "saved"}


class SaveConfigBody(BaseModel):
    provider_id:      str
    model:            str
    temperature:      float
    max_tokens:       int
    allowed_tools:    list
    can_spawn:        bool
    spawnable_agents: list = []
    max_iterations:   int
    tags:             list = []
    in_salon:         bool = False
    in_battle:        bool = False

@app.put("/agents/{agent_name}/config")
async def save_config(agent_name: str, body: SaveConfigBody):
    agent = _agents.get(agent_name)
    if not agent: return {"error": f"Agent '{agent_name}' non trouvé"}

    # Préserver les context_limits existantes
    config_file = agent.path / "config.json"
    existing_limits = {}
    if config_file.exists():
        try:
            existing = json.loads(config_file.read_text(encoding="utf-8"))
            existing_limits = existing.get("context_limits", {})
        except Exception:
            pass

    save_agent_config(agent.path, {
        "provider_id":       body.provider_id,
        "model":             body.model,
        "temperature":       body.temperature,
        "max_tokens":        body.max_tokens,
        "allowed_tools":     body.allowed_tools,
        "can_spawn":         body.can_spawn,
        "spawnable_agents":  body.spawnable_agents,
        "max_iterations":    body.max_iterations,
        "tags":              body.tags,
        "in_salon":          body.in_salon,
        "in_battle":         body.in_battle,
        "context_limits": existing_limits or {
            "total": 3000, "system": 600, "history": 1000,
            "rag": 800, "tools": 300, "user": 300,
        },
    })
    reloaded = load_agent(agent.path)
    if reloaded: _agents[agent_name] = reloaded
    return {"status": "saved"}


class AgentContextLimitsBody(BaseModel):
    total:   int
    system:  int
    history: int
    rag:     int
    tools:   int
    user:    int

@app.put("/agents/{agent_name}/context-limits")
async def save_agent_context_limits(agent_name: str, body: AgentContextLimitsBody):
    """
    Met à jour les limites de contexte d'un agent.
    Règle : system + history + rag + tools + user doit être ≤ total.
    Si la somme dépasse le max, la config est refusée.
    """
    agent = _agents.get(agent_name)
    if not agent: return {"error": f"Agent '{agent_name}' non trouvé"}

    parts_sum = body.system + body.history + body.rag + body.tools + body.user
    if parts_sum > body.total:
        return {
            "error": f"La somme des composantes ({parts_sum} tokens) dépasse le max ({body.total}). Config non sauvegardée.",
            "current": agent.config.limits.to_dict(),
        }

    config_file = agent.path / "config.json"
    data = {}
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    new_limits = {
        "total":   body.total,
        "system":  body.system,
        "history": body.history,
        "rag":     body.rag,
        "tools":   body.tools,
        "user":    body.user,
    }
    data["context_limits"] = new_limits
    config_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    reloaded = load_agent(agent.path)
    if reloaded: _agents[agent_name] = reloaded

    return {"status": "saved", "limits": new_limits}


@app.delete("/agents/{agent_name}")
async def delete_agent(agent_name: str):
    agent = _agents.get(agent_name)
    if not agent: return {"error": f"Agent '{agent_name}' non trouvé"}
    shutil.rmtree(agent.path, ignore_errors=True)
    _agents.pop(agent_name, None)
    _agent_sessions.pop(agent_name, None)
    return {"status": "deleted"}


# ─── Providers ────────────────────────────────────────────────────────────────

@app.get("/providers")
async def get_providers():
    providers = _load_providers()
    # Masquer les clés dans la réponse
    safe = {}
    for pid, p in providers.items():
        k = p.get("key", "")
        safe[pid] = {
            **p,
            "key": ("*" * (len(k) - 4) + k[-4:]) if len(k) > 4 else ("****" if k else ""),
        }
    return {"providers": safe}


class SaveProviderBody(BaseModel):
    id:       str
    label:    str
    endpoint: str
    key:      str = ""
    models:   list = []

@app.post("/providers")
async def save_provider(body: SaveProviderBody):
    providers = _load_providers()
    pid = body.id.strip()
    if not pid:
        return {"error": "ID provider invalide"}
    existing_key = providers.get(pid, {}).get("key", "")
    providers[pid] = {
        "label":    body.label,
        "endpoint": body.endpoint.rstrip("/"),
        "key":      body.key if body.key and not body.key.startswith("*") else existing_key,
        "models":   body.models,
    }
    _save_providers(providers)
    set_providers(providers)
    return {"status": "saved", "id": pid}


@app.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str):
    providers = _load_providers()
    providers.pop(provider_id, None)
    _save_providers(providers)
    set_providers(providers)
    return {"status": "deleted"}


# ─── Débat ────────────────────────────────────────────────────────────────────

class StartDebateBody(BaseModel):
    topic:      str
    agents:     list
    turns:      int
    session_id: str
    force_vote: bool = False

@app.post("/debate")
async def start_debate(body: StartDebateBody):
    agents = [_agents[n] for n in body.agents if n in _agents]
    if len(agents) < 2:
        return {"error": "Il faut au moins 2 agents valides pour un débat."}
    if not body.topic.strip():
        return {"error": "Le sujet ne peut pas être vide."}

    debate_id  = str(uuid4())
    session_id = body.session_id
    _debate_cancelled[debate_id] = False

    async def ws_cb(event):
        ws = _websockets.get(session_id)
        if ws:
            try: await ws.send_json(event)
            except Exception: pass

    async def log_cb(level, msg):
        await ws_cb({"type": "log", "data": {"level": level, "message": msg}})

    asyncio.create_task(run_debate(
        debate_id       = debate_id,
        topic           = body.topic,
        agents          = agents,
        turns           = body.turns,
        ws_callback     = ws_cb,
        log_callback    = log_cb,
        cancelled_flags = _debate_cancelled,
        force_vote      = body.force_vote,
    ))
    return {"status": "started", "debate_id": debate_id}


@app.post("/debate/{debate_id}/stop")
async def stop_debate(debate_id: str):
    if debate_id not in _debate_cancelled:
        return {"error": "Débat introuvable."}
    _debate_cancelled[debate_id] = True
    return {"status": "stopping"}


# ─── Battle Royale ────────────────────────────────────────────────────────────

class StartBattleBody(BaseModel):
    agents:     list
    session_id: str

@app.post("/battle")
async def start_battle(body: StartBattleBody):
    agents = [_agents[n] for n in body.agents if n in _agents]
    if len(agents) < 3:
        return {"error": "Il faut au moins 3 agents pour un Battle Royale."}

    battle_id  = str(uuid4())
    session_id = body.session_id
    _battle_cancelled[battle_id] = False

    async def ws_cb(event):
        ws = _websockets.get(session_id)
        if ws:
            try: await ws.send_json(event)
            except Exception: pass

    async def log_cb(level, msg):
        await ws_cb({"type": "log", "data": {"level": level, "message": msg}})

    asyncio.create_task(run_battle(
        battle_id       = battle_id,
        agents          = agents,
        ws_callback     = ws_cb,
        log_callback    = log_cb,
        cancelled_flags = _battle_cancelled,
    ))
    return {"status": "started", "battle_id": battle_id}


@app.post("/battle/{battle_id}/stop")
async def stop_battle(battle_id: str):
    if battle_id not in _battle_cancelled:
        return {"error": "Battle introuvable."}
    _battle_cancelled[battle_id] = True
    return {"status": "stopping"}


# ─── Tools ────────────────────────────────────────────────────────────────────

@app.get("/tools")
async def get_all_tools():
    return {"tools": list(ALL_TOOLS_SCHEMA.values()), "all_names": ALL_TOOLS}


# ─── Chat ─────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message:    str
    session_id: str

@app.post("/agents/{agent_name}/chat")
async def chat(agent_name: str, body: ChatMessage):
    agent = _agents.get(agent_name)
    if not agent: return {"error": f"Agent '{agent_name}' non trouvé"}

    if agent_name not in _agent_sessions:
        _agent_sessions[agent_name] = {"history": [], "messages": []}

    ws = _websockets.get(body.session_id)

    async def log_callback(log_type: str, msg: str):
        if ws:
            try: await ws.send_json({"type": "log", "data": {"level": log_type, "message": msg}})
            except Exception: pass

    asyncio.create_task(
        _run_agent_task(agent, body.message, agent_name, body.session_id, log_callback)
    )
    return {"status": "processing", "session_id": body.session_id}


async def _run_agent_task(agent, user_message, agent_name, ws_session_id, log_callback):
    ws      = _websockets.get(ws_session_id)
    session = _agent_sessions.get(agent_name, {"history": [], "messages": []})
    history = session["history"]

    session["messages"].append({"role": "user", "content": user_message})

    stop_flag = {"cancelled": False}
    _agent_stop_flags[agent_name] = stop_flag

    try:
        async for event in run_agent(
            agent            = agent,
            user_message     = user_message,
            history          = history,
            rag_engine       = _shared_rag,
            log_callback     = log_callback,
            _agents_registry = _agents,
            _stop_flag       = stop_flag,
        ):
            if ws:
                try: await ws.send_json(event)
                except Exception: pass

            source     = event.get("source_agent", agent.name)
            is_child   = source != agent.name
            event_type = event["type"]

            if event_type == "tool_call" and event["data"]["name"] == "spawn_agent":
                params = event["data"]["params"]
                session["messages"].append({
                    "role": "spawn_request",
                    "from": source,
                    "to":   params.get("agent_name", "?"),
                    "task": params.get("task", ""),
                })

            elif event_type == "partial_response":
                session["messages"].append({
                    "role":    "partial",
                    "content": event["data"]["content"],
                    "agent":   event["data"].get("agent_name", agent.name),
                })

            elif event_type == "response":
                if is_child:
                    session["messages"].append({
                        "role":    "sub_agent",
                        "content": event["data"]["content"],
                        "agent":   source,
                    })
                else:
                    final_content = event["data"]["content"]
                    history.append({"role": "user",      "content": user_message})
                    history.append({"role": "assistant",  "content": final_content})
                    if len(history) > 40:
                        history = history[-40:]
                    session["messages"].append({"role": "assistant", "content": final_content})
                    session["history"] = history
                    _agent_sessions[agent_name] = session

    except Exception as e:
        if ws:
            try:
                await ws.send_json({"type": "log",  "data": {"level": "error", "message": f"❌ {e}"}})
                await ws.send_json({"type": "done",  "data": {}})
            except Exception: pass
    finally:
        _agent_stop_flags.pop(agent_name, None)


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    _websockets[session_id] = websocket
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _websockets.pop(session_id, None)


# ─── Frontend statique ────────────────────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# ─── Fonctions internes ───────────────────────────────────────────────────────

def _reload_all_agents():
    _agents.clear()
    for agent in discover_agents(AGENTS_DIR):
        _agents[agent.name] = agent


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
