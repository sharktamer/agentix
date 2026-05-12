"""
orchestrator.py
===============
L'orchestrateur est le "chef d'orchestre" du système agentique.
Gère la boucle agentique, les tool calls, le spawn de sous-agents et la propagation du stop flag.
"""

import json
import asyncio
from typing import AsyncGenerator

import httpx

from context.context_manager import build_context, ContextLimits
from orchestrator.agent_loader import Agent
from rag.rag_engine import RAGEngine
from tools.tools import execute_tool, get_tools_schema_for_agent, get_tools_description_for_agent

MAX_SPAWN_DEPTH = 2
MAX_SPAWN_COUNT = 5
SPAWN_TIMEOUT   = 600


async def run_agent(
    agent:            Agent,
    user_message:     str,
    history:          list,
    rag_engine:       RAGEngine,
    log_callback,
    limits:           ContextLimits = None,
    _spawn_depth:     int  = 0,
    _source_agent:    str  = None,
    _agents_registry: dict = None,
    _stop_flag:       dict = None,
) -> AsyncGenerator[dict, None]:
    """
    Exécute l'agent complet et génère des événements en temps réel.

    Événements émis (tous ont un champ optionnel source_agent) :
    - log             : message de log système
    - token_update    : mise à jour de la jauge de tokens
    - tool_call       : un tool est demandé
    - tool_result     : résultat d'un tool
    - partial_response: message intermédiaire (l'agent continue ensuite)
    - spawn_event     : événement provenant d'un sous-agent (avec source_agent)
    - response        : réponse finale
    - done            : signal de fin
    """
    L           = limits or agent.config.limits
    spawn_count = 0
    source      = _source_agent or agent.name

    def _wrap(event: dict) -> dict:
        """Ajoute source_agent à tous les événements pour l'UI."""
        event["source_agent"] = source
        return event

    # ── RAG ───────────────────────────────────────────────────────────────────
    await log_callback("info", "🔍 Recherche RAG en cours...")
    rag_chunks = []

    if rag_engine:
        rag_chunks = rag_engine.search(user_message)
        msg = f"✅ RAG : {len(rag_chunks)} chunk(s)" if rag_chunks else "ℹ️  RAG : aucun résultat (KB vide ?)"
        await log_callback("rag", msg)

    # ── Contexte ──────────────────────────────────────────────────────────────
    await log_callback("info", "📐 Construction du contexte...")

    tools_desc = get_tools_description_for_agent(agent.config.allowed_tools)

    # Injecter les descriptions des sous-agents autorisés (compte dans le budget tools)
    if "spawn_agent" in agent.config.allowed_tools and agent.config.spawnable_agents and _agents_registry:
        lines = ["\nAgents disponibles pour spawn :"]
        for child_name in agent.config.spawnable_agents:
            child = _agents_registry.get(child_name)
            if child:
                role = child.metadata.get("role", "agent spécialisé")
                lines.append(f"- {child_name} : {role}")
        tools_desc += "\n".join(lines)

    context    = build_context(
        system_prompt     = agent.system_prompt,
        history           = history,
        rag_chunks        = rag_chunks,
        tools_description = tools_desc,
        user_message      = user_message,
        limits            = L,
    )

    yield _wrap({"type": "token_update", "data": context["token_breakdown"]})

    for log_msg in context["logs"]:
        await log_callback("context", log_msg)

    if context["was_trimmed"]:
        await log_callback("context", "⚠️  Contexte ajusté pour respecter la limite de tokens")

    await log_callback("info",
        f"📊 Contexte : {context['token_breakdown']['total']} / {context['token_breakdown']['max']} tokens"
    )

    agent_tools = get_tools_schema_for_agent(agent.config.allowed_tools)
    await log_callback("info", f"🔧 Tools : {', '.join(agent.config.allowed_tools)}")

    # ── Boucle agentique ──────────────────────────────────────────────────────
    messages       = context["messages"]
    iteration      = 0
    final_response = None
    max_iter       = agent.config.max_iterations

    while iteration < max_iter:
        if _stop_flag and _stop_flag.get("cancelled"):
            await log_callback("info", "⏹ Arrêt demandé — exécution interrompue")
            final_response = "⏹ Exécution interrompue par l'utilisateur."
            break

        iteration += 1
        await log_callback("info", f"🤖 Appel LLM (itération {iteration}/{max_iter})...")

        llm_response = await _call_llm(
            endpoint    = get_provider_endpoint(agent.config.provider_id),
            model       = agent.config.model,
            messages    = messages,
            temperature = agent.config.temperature,
            max_tokens  = agent.config.max_tokens,
            tools       = agent_tools or None,
        )

        if "error" in llm_response:
            await log_callback("error", f"❌ Erreur LLM : {llm_response['error']}")
            final_response = f"Erreur LM Studio : {llm_response['error']}"
            break

        choice  = llm_response.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish  = choice.get("finish_reason", "stop")

        # ── Tool calls ────────────────────────────────────────────────────────
        if finish == "tool_calls" or message.get("tool_calls"):
            tool_calls = message.get("tool_calls", [])

            # Feature 4 : si le LLM a aussi produit du texte avant les tool calls,
            # l'émettre comme message intermédiaire plutôt que de le perdre
            if interim_text := (message.get("content") or "").strip():
                await log_callback("info", f"💬 Message intermédiaire de l'agent")
                yield _wrap({"type": "partial_response", "data": {
                    "content":    interim_text,
                    "agent_name": agent.name,
                    "iteration":  iteration,
                }})
                # Ajouter à l'historique de messages pour maintenir la cohérence
                messages.append({"role": "assistant", "content": interim_text})

            for tool_call in tool_calls:
                tool_name   = tool_call["function"]["name"]
                tool_params = json.loads(tool_call["function"].get("arguments", "{}"))

                # Vérification de sécurité
                if tool_name not in agent.config.allowed_tools:
                    await log_callback("error", f"🚫 Tool refusé : {tool_name}")
                    result = {"success": False, "error": f"Tool '{tool_name}' non autorisé."}
                    messages.append({"role": "assistant", "content": None, "tool_calls": [tool_call]})
                    messages.append({"role": "tool", "tool_call_id": tool_call["id"], "content": json.dumps(result)})
                    continue

                await log_callback("tool", f"🔧 Tool : {tool_name}({_format_params(tool_params)})")
                yield _wrap({"type": "tool_call", "data": {"name": tool_name, "params": tool_params}})

                # ── spawn_agent ───────────────────────────────────────────────
                if tool_name == "spawn_agent":
                    child_name = tool_params.get("agent_name", "?")
                    await log_callback("tool", f"🌿 Spawn → {child_name} (profondeur {_spawn_depth + 1})")

                    # Collecter tous les événements du sous-agent et les remonter
                    child_events = []
                    result = await _handle_spawn(
                        params           = tool_params,
                        parent_agent     = agent,
                        spawn_depth      = _spawn_depth,
                        spawn_count      = spawn_count,
                        agents_registry  = _agents_registry or {},
                        rag_engine       = rag_engine,
                        log_callback     = log_callback,
                        event_collector  = child_events,
                        stop_flag        = _stop_flag,
                    )
                    spawn_count += 1

                    # Remonter les événements du sous-agent avec leur source
                    for child_event in child_events:
                        yield child_event  # déjà wrappé avec source_agent=child_name

                    yield _wrap({"type": "spawn_end", "data": {
                        "agent_name": child_name,
                        "result":     result.get("result", ""),
                        "success":    result.get("success", False),
                    }})

                # ── Tool normal ───────────────────────────────────────────────
                else:
                    await log_callback("tool", f"⚙️  Exécution de {tool_name}...")
                    result = await asyncio.to_thread(execute_tool, tool_name, tool_params, agent.name, rag_engine)

                ok = result.get("success", False)
                await log_callback("tool",
                    f"{'✅' if ok else '❌'} {tool_name} : {str(result.get('result' if ok else 'error', ''))[:80]}"
                )
                yield _wrap({"type": "tool_result", "data": result})

                messages.append({"role": "assistant", "content": None, "tool_calls": [tool_call]})
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call["id"],
                    "content":      json.dumps(result),
                })

        # ── Réponse texte du LLM ──────────────────────────────────────────────
        else:
            content = message.get("content", "")

            # Feature 4 : détecter si c'est un message intermédiaire ou final.
            # Heuristique : si le LLM dit explicitement qu'il continue,
            # on émet un partial_response et on laisse la boucle continuer.
            # En pratique avec des petits modèles locaux, la plupart des réponses
            # texte sont finales — on les traite donc comme telles par défaut.
            # Pour activer le mode "continue", l'agent doit avoir max_iterations > 1
            # et le LLM doit retourner un tool_call à l'itération suivante.
            final_response = content
            await log_callback("info", "✅ Réponse finale générée")
            break

    if not final_response:
        final_response = "L'agent n'a pas pu générer de réponse."

    yield _wrap({"type": "response",     "data": {"content": final_response}})
    yield _wrap({"type": "token_update", "data": context["token_breakdown"]})
    yield _wrap({"type": "done",         "data": {}})


async def _handle_spawn(
    params, parent_agent, spawn_depth, spawn_count,
    agents_registry, rag_engine, log_callback, event_collector: list,
    stop_flag: dict = None,
) -> dict:
    """
    Exécute un sous-agent séquentiellement.
    Tous les événements sont collectés dans event_collector
    pour être remontés au frontend par l'appelant.
    """
    child_name = params.get("agent_name", "")
    task       = params.get("task", "")
    context    = params.get("context", "")

    if not parent_agent.config.can_spawn:
        return {"success": False, "error": "can_spawn=false sur cet agent."}
    if spawn_depth >= MAX_SPAWN_DEPTH:
        return {"success": False, "error": f"Profondeur max ({MAX_SPAWN_DEPTH}) atteinte."}
    if spawn_count >= MAX_SPAWN_COUNT:
        return {"success": False, "error": f"Max spawns ({MAX_SPAWN_COUNT}) atteint."}

    # Vérifier la whitelist spawnable_agents (liste vide = pas de restriction)
    allowed_spawnable = parent_agent.config.spawnable_agents
    if allowed_spawnable and child_name not in allowed_spawnable:
        return {"success": False, "error": f"Agent '{child_name}' non autorisé. Agents autorisés : {allowed_spawnable}"}

    child_agent = agents_registry.get(child_name)
    if not child_agent:
        return {"success": False, "error": f"Agent '{child_name}' introuvable. Disponibles : {list(agents_registry.keys())}"}

    full_task = task
    if context:
        full_task = f"{task}\n\nContexte du parent :\n{context}"

    response_acc  = []

    async def child_log(level, msg):
        await log_callback(level, f"  [{child_name}] {msg}")

    try:
        async def _run():
            async for event in run_agent(
                agent            = child_agent,
                user_message     = full_task,
                history          = [],
                rag_engine       = rag_engine,
                log_callback     = child_log,
                _spawn_depth     = spawn_depth + 1,
                _source_agent    = child_name,
                _agents_registry = agents_registry,
                _stop_flag       = stop_flag,
            ):
                # Collecter tous les événements pour les remonter au parent
                event_collector.append(event)
                if event["type"] == "response":
                    response_acc.append(event["data"]["content"])

        await asyncio.wait_for(_run(), timeout=SPAWN_TIMEOUT)

    except asyncio.TimeoutError:
        await log_callback("error", f"⏱️  [{child_name}] Timeout ({SPAWN_TIMEOUT}s)")
        return {"success": False, "error": f"Timeout {SPAWN_TIMEOUT}s"}
    except Exception as e:
        await log_callback("error", f"❌ [{child_name}] Erreur : {e}")
        return {"success": False, "error": str(e)}

    result_text = response_acc[0] if response_acc else "(pas de réponse)"
    await log_callback("tool", f"✅ [{child_name}] Terminé")
    return {"success": True, "result": result_text, "spawned": True}


_providers: dict = {}


def set_providers(providers: dict):
    global _providers
    _providers = dict(providers)


def get_provider_endpoint(provider_id: str) -> str:
    return _providers.get(provider_id, {}).get("endpoint", "")


def _get_api_key(endpoint: str) -> str:
    for p in _providers.values():
        if p.get("endpoint", "").rstrip("/") == endpoint.rstrip("/"):
            return p.get("key", "")
    return ""


async def _call_llm(endpoint, model, messages, temperature, max_tokens, tools=None):
    if not endpoint:
        return {"error": "Aucun provider configuré pour cet agent. Configure-le dans l'éditeur."}
    if not model:
        return {"error": "Aucun modèle configuré pour cet agent. Configure-le dans l'éditeur."}
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
    headers = {"Content-Type": "application/json"}
    key = _get_api_key(endpoint)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(f"{endpoint}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        return {"error": f"Impossible de se connecter à {endpoint}."}
    except httpx.TimeoutException:
        return {"error": "Timeout LLM."}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code} — {e.response.text[:120]}"}
    except Exception as e:
        return {"error": str(e)}


def _format_params(params):
    parts = []
    for k, v in params.items():
        s = str(v)[:40] + "..." if len(str(v)) > 40 else str(v)
        parts.append(f"{k}={repr(s)}")
    return ", ".join(parts)
