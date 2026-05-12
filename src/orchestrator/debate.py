"""
debate.py
=========
Salon de débat multi-agents.

Chaque agent reçoit l'historique du débat tronqué à ses propres limites
de contexte (config.limits.history). Un agent avec peu de tokens ne voit
que les derniers messages ; un agent avec plus voit plus loin en arrière.
"""

import asyncio

from context.context_manager import count_tokens
from orchestrator.orchestrator import _call_llm, get_provider_endpoint


def build_debate_system(agent, topic: str, participant_names: list) -> str:
    """System prompt = personnalité de l'agent + contexte du débat."""
    others = [n for n in participant_names if n != agent.name]
    others_str = ", ".join(others) if others else "personne d'autre"
    debate_ctx = (
        f"\n\n--- Contexte du débat ---\n"
        f"Tu es {agent.name}. Tu participes à un débat avec : {others_str}.\n"
        f"Sujet : {topic}\n"
        f"Réponds directement au dernier message. Reste dans ton personnage, sois concis."
    )
    return agent.system_prompt + debate_ctx


def _trim_history_entries(entries: list, limit: int) -> tuple[list, int]:
    """Retourne (selected, total_skipped) en gardant les messages les plus récents."""
    selected = []
    used = 0
    for entry in reversed(entries):
        t = count_tokens(entry)
        if used + t > limit:
            break
        selected.insert(0, entry)
        used += t
    if not selected and entries:
        selected = [entries[-1]]
    return selected, len(entries) - len(selected)


def build_debate_user_message(history: list, limits) -> str:
    """
    Construit le message 'user' à partir de l'historique partagé du débat.
    Tronqué par la fin pour respecter limits.history de l'agent courant.
    """
    if not history:
        return "C'est le début du débat. Lance la discussion sur le sujet."

    entries = [f"[{h['agent']}]: {h['content']}" for h in history]
    selected, skipped = _trim_history_entries(entries, limits.history)

    prefix = f"[… {skipped} message(s) précédent(s) non affichés — limite de contexte]\n" if skipped else ""
    return prefix + "\n".join(selected) + "\n\nC'est ton tour de répondre."


def build_vote_user_message(topic: str, history: list, limits) -> str:
    """Message de vote : transcript du débat + instruction de vote explicite."""
    if not history:
        transcript = "(aucun échange)"
    else:
        entries = [f"[{h['agent']}]: {h['content']}" for h in history]
        selected, skipped = _trim_history_entries(entries, limits.history)
        prefix = f"[… {skipped} message(s) non affichés]\n" if skipped else ""
        transcript = prefix + "\n".join(selected)

    return (
        f"Voici le débat qui vient de se dérouler sur le sujet : « {topic} »\n\n"
        f"{transcript}\n\n"
        f"Le débat est terminé. Tu dois maintenant voter.\n"
        f"Commence OBLIGATOIREMENT ta réponse par exactement 'VOTE: POUR' ou 'VOTE: CONTRE', "
        f"puis justifie ton vote en 2-3 phrases."
    )


def parse_vote(content: str) -> str:
    """Extrait POUR / CONTRE / INDÉTERMINÉ depuis le début de la réponse."""
    first = content.strip().split('\n')[0].upper()
    if "VOTE: POUR" in first or "VOTE:POUR" in first:
        return "POUR"
    if "VOTE: CONTRE" in first or "VOTE:CONTRE" in first:
        return "CONTRE"
    return "INDÉTERMINÉ"


async def _emit_tokens(ws_callback, agent, sys_tok: int, msg_tok: int):
    L = agent.config.limits
    total = sys_tok + msg_tok
    await ws_callback({"type": "token_update", "data": {
        "system": sys_tok, "history": 0, "rag": 0, "tools": 0,
        "user": msg_tok, "total": total, "max": L.total,
        "percent": round((total / L.total) * 100) if L.total else 0,
        "limits": L.to_dict(),
    }})


async def run_debate(
    debate_id:       str,
    topic:           str,
    agents:          list,
    turns:           int,
    ws_callback,
    log_callback,
    cancelled_flags: dict,
    force_vote:      bool = False,
):
    """
    Boucle principale du débat.
    Si force_vote=True, chaque agent effectue un appel LLM supplémentaire
    après le débat pour voter POUR ou CONTRE la proposition.
    """
    history = []
    votes   = {}

    try:
        await ws_callback({"type": "debate_start", "data": {
            "topic": topic, "agents": [a.name for a in agents],
            "turns": turns, "force_vote": force_vote,
        }})
        await log_callback("info", f"🎭 Débat démarré — sujet : {topic}")

        participant_names = [a.name for a in agents]

        for round_num in range(turns):
            for agent in agents:
                if cancelled_flags.get(debate_id):
                    break

                await log_callback("info", f"🎭 [{agent.name}] — tour {round_num + 1}/{turns}")
                await ws_callback({"type": "debate_thinking", "data": {
                    "agent": agent.name, "round": round_num + 1,
                }})

                system   = build_debate_system(agent, topic, participant_names)
                user_msg = build_debate_user_message(history, agent.config.limits)
                await _emit_tokens(ws_callback, agent, count_tokens(system), count_tokens(user_msg))

                result = await _call_llm(
                    endpoint    = get_provider_endpoint(agent.config.provider_id),
                    model       = agent.config.model,
                    messages    = [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user_msg},
                    ],
                    temperature = agent.config.temperature,
                    max_tokens  = agent.config.max_tokens,
                    tools       = None,
                )

                if "error" in result:
                    err = result["error"]
                    await log_callback("error", f"❌ [{agent.name}] {err}")
                    await ws_callback({"type": "debate_turn", "data": {
                        "agent": agent.name, "content": f"[Erreur : {err}]",
                        "round": round_num + 1, "error": True,
                    }})
                    continue

                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                history.append({"agent": agent.name, "content": content})
                await log_callback("info", f"✅ [{agent.name}] {count_tokens(content)} tokens")
                await ws_callback({"type": "debate_turn", "data": {
                    "agent": agent.name, "content": content, "round": round_num + 1,
                }})

            if cancelled_flags.get(debate_id):
                await log_callback("info", "⏹ Débat interrompu")
                break

        # ── Phase de vote ──────────────────────────────────────────────────────
        if force_vote and not cancelled_flags.get(debate_id):
            await log_callback("info", "🗳️ Phase de vote...")
            await ws_callback({"type": "debate_vote_start", "data": {}})

            for agent in agents:
                await log_callback("info", f"🗳️ [{agent.name}] vote en cours...")
                await ws_callback({"type": "debate_thinking", "data": {
                    "agent": agent.name, "round": "vote",
                }})

                system   = build_debate_system(agent, topic, participant_names)
                vote_msg = build_vote_user_message(topic, history, agent.config.limits)
                await _emit_tokens(ws_callback, agent, count_tokens(system), count_tokens(vote_msg))

                result = await _call_llm(
                    endpoint    = get_provider_endpoint(agent.config.provider_id),
                    model       = agent.config.model,
                    messages    = [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": vote_msg},
                    ],
                    temperature = 0.3,
                    max_tokens  = agent.config.max_tokens,
                    tools       = None,
                )

                if "error" in result:
                    vote, reason = "ERREUR", result["error"]
                else:
                    content      = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    vote, reason = parse_vote(content), content

                votes[agent.name] = vote
                await log_callback("info", f"🗳️ [{agent.name}] → {vote}")
                await ws_callback({"type": "debate_vote", "data": {
                    "agent": agent.name, "vote": vote, "reason": reason,
                }})

    except Exception as e:
        await log_callback("error", f"❌ Erreur débat : {e}")

    finally:
        cancelled_flags.pop(debate_id, None)
        await ws_callback({"type": "debate_done", "data": {
            "total_turns": len(history),
            "votes":       votes or None,
        }})
