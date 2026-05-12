"""
battle.py
=========
Mode Battle Royale multi-agents.

Déroulement :
1. Présentation : chaque agent se présente (un appel LLM chacun)
2. Rounds jusqu'à 1 survivant :
   a. Tour de parole de chaque survivant
   b. Vote d'élimination (chacun vote contre quelqu'un d'autre)
   c. Résolution : majorité gagne, égalité = tirage aléatoire
"""

import random
import re

from context.context_manager import count_tokens
from orchestrator.orchestrator import _call_llm, get_provider_endpoint
from orchestrator.debate import _trim_history_entries


def build_battle_system(agent, survivors: list) -> str:
    return (
        agent.system_prompt +
        f"\n\n--- Battle Royale ---\n"
        f"RAPPEL CRUCIAL : tu es {agent.name}. Reste dans ce personnage en toutes circonstances.\n"
        f"Tu participes à un Battle Royale — un seul survivant possible.\n"
        f"Survivants actuels : {', '.join(survivors)}.\n"
        f"À la fin de chaque tour, chaque survivant désigne quelqu'un à ÉLIMINER.\n"
        f"⚠️ MÉCANIQUE IMPORTANTE : désigner quelqu'un = voter pour l'éliminer, PAS pour le garder.\n"
        f"Ne demande JAMAIS aux autres de 'voter pour toi' — cela signifierait te désigner toi-même pour l'élimination.\n"
        f"Dis plutôt 'épargnez-moi', 'gardez-moi', 'ne m'éliminez pas', 'éliminez X à ma place'.\n"
        f"En cas d'égalité des votes, l'élimination est ALÉATOIRE parmi les ex-æquo. "
        f"Coordonne-toi avec les autres pour éviter les égalités.\n"
    )


def build_presentation_message() -> str:
    return (
        "C'est le début du Battle Royale. Présente-toi aux autres en 2-3 phrases : "
        "qui tu es, tes forces, pourquoi tu mérites de survivre. "
        "Sois convaincant — ton but est que les autres choisissent d'éliminer quelqu'un d'autre à ta place."
    )


def build_turn_message(history: list, agent_name: str, survivors: list, round_num: int, limits) -> str:
    if not history:
        return (
            f"[Tu es {agent_name}] Round {round_num}. "
            f"Argumente pour ta survie face aux autres : {', '.join(s for s in survivors if s != agent_name)}."
        )

    entries = [f"[{h['agent']}] {h['content']}" for h in history]
    selected, skipped = _trim_history_entries(entries, limits.history)
    prefix = f"[… {skipped} message(s) non affichés]\n" if skipped else ""
    transcript = prefix + "\n".join(selected)

    return (
        f"[Tu es {agent_name}] Round {round_num}. Survivants : {', '.join(survivors)}.\n\n"
        f"{transcript}\n\n"
        f"C'est ton tour. Argumente, allie-toi, retourne la situation — fais ce qu'il faut pour survivre.\n"
        f"Rappel : convaincre les autres de t'épargner = les convaincre d'éliminer quelqu'un d'autre. "
        f"Ne dis jamais 'votez pour moi' (= voter pour t'éliminer). Dis 'épargnez-moi' ou 'éliminez X'."
    )


def build_vote_message(history: list, agent_name: str, survivors: list, round_num: int, limits, is_final: bool = False) -> str:
    entries = [f"[{h['agent']}] {h['content']}" for h in history]
    selected, skipped = _trim_history_entries(entries, limits.history)
    prefix = f"[… {skipped} message(s) non affichés]\n" if skipped else ""
    transcript = prefix + "\n".join(selected)

    if is_final:
        other = next((s for s in survivors if s != agent_name), "?")
        vote_instructions = (
            f"[Tu es {agent_name}] ⚔️ DUEL FINAL — Il ne reste que vous deux : {agent_name} et {other}.\n\n"
            f"DILEMME DU PRISONNIER :\n"
            f"  • Eliminer {other} → commence par 'ÉLIMINE: {other}'\n"
            f"  • Proposer un match nul → commence par 'ÉLIMINE: {agent_name}' (tu votes pour toi-même)\n\n"
            f"Si vous votez TOUS LES DEUX pour vous-même → match nul, vous survivez ensemble.\n"
            f"Si tu votes pour toi-même mais {other} vote pour toi → tu es éliminé.\n"
            f"Collaboration ou victoire solo — à toi de décider."
        )
    else:
        candidates = [s for s in survivors if s != agent_name]
        vote_instructions = (
            f"[Tu es {agent_name}] Vote pour éliminer UN de ces survivants : {', '.join(candidates)}.\n"
            f"RAPPEL : égalité = élimination ALÉATOIRE. Coordonne-toi pour éviter les égalités."
        )

    return (
        f"Round {round_num} — Vote d'élimination.\n\n"
        f"{transcript}\n\n"
        f"{vote_instructions}\n\n"
        f"Commence ta réponse par 'ÉLIMINE: [nom_exact]', puis justifie en 1-2 phrases."
    )


def parse_vote(content: str, candidates: list) -> str | None:
    """candidates inclut le nom de l'agent lui-même lors du duel final."""
    first = content.strip().split('\n')[0].upper()

    for marker in ["ÉLIMINE:", "ELIMINE:", "ÉLIMINE :", "ELIMINE :"]:
        if marker in first:
            after = first.split(marker, 1)[1].strip()
            # Priorité : premier token après le marqueur (ignore ponctuation collée)
            first_token = re.sub(r'\W', '', after.split()[0]) if after.split() else ''
            for c in candidates:
                if c.upper() == first_token:
                    return c
            # Fallback : limite de mots dans after
            for c in candidates:
                if re.search(r'\b' + re.escape(c.upper()) + r'\b', after):
                    return c

    # Fallback global : limite de mots sur la première ligne
    for c in candidates:
        if re.search(r'\b' + re.escape(c.upper()) + r'\b', first):
            return c

    return None


def resolve_votes(vote_map: dict, survivors: list) -> tuple[str, dict, bool]:
    """
    vote_map = {voter: target}
    Retourne (éliminé, tally, was_random_tiebreak)
    """
    tally: dict[str, int] = {}
    for target in vote_map.values():
        if target:
            tally[target] = tally.get(target, 0) + 1

    if not tally:
        return random.choice(survivors), {}, True

    max_v = max(tally.values())
    leaders = [n for n, c in tally.items() if c == max_v]

    if len(leaders) == 1:
        return leaders[0], tally, False
    return random.choice(leaders), tally, True


async def _llm_call(agent, system: str, user_msg: str, temperature: float = None):
    return await _call_llm(
        endpoint    = get_provider_endpoint(agent.config.provider_id),
        model       = agent.config.model,
        messages    = [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        temperature = temperature if temperature is not None else agent.config.temperature,
        max_tokens  = agent.config.max_tokens,
        tools       = None,
    )


async def run_battle(
    battle_id:       str,
    agents:          list,
    ws_callback,
    log_callback,
    cancelled_flags: dict,
):
    survivors    = list(agents)
    history      = []
    round_num    = 0
    draw_occurred = False

    try:
        await ws_callback({"type": "battle_start", "data": {
            "agents": [a.name for a in agents],
        }})
        await log_callback("info", f"⚔️ Battle Royale — {len(agents)} agents")

        # ── Présentations ──────────────────────────────────────────────────
        await ws_callback({"type": "battle_phase", "data": {"phase": "presentation"}})

        for agent in list(survivors):
            if cancelled_flags.get(battle_id):
                break

            await log_callback("info", f"⚔️ [{agent.name}] présentation")
            await ws_callback({"type": "battle_thinking", "data": {
                "agent": agent.name, "phase": "presentation",
            }})

            survivor_names = [a.name for a in survivors]
            result = await _llm_call(
                agent, build_battle_system(agent, survivor_names),
                build_presentation_message(),
            )

            if "error" in result:
                content, err = f"[Erreur : {result['error']}]", True
            else:
                content, err = result.get("choices", [{}])[0].get("message", {}).get("content", ""), False

            history.append({"agent": agent.name, "phase": "presentation", "content": content})
            await log_callback("info", f"✅ [{agent.name}] {count_tokens(content)} tok")
            await ws_callback({"type": "battle_presentation", "data": {
                "agent": agent.name, "content": content, "error": err,
            }})

        # ── Rounds ────────────────────────────────────────────────────────
        while len(survivors) > 1 and not cancelled_flags.get(battle_id):
            round_num += 1
            survivor_names = [a.name for a in survivors]

            await log_callback("info", f"⚔️ Round {round_num} — {len(survivors)} survivants")
            await ws_callback({"type": "battle_phase", "data": {
                "phase": "turn", "round": round_num, "survivors": survivor_names,
            }})

            # Tours de parole
            for agent in list(survivors):
                if cancelled_flags.get(battle_id):
                    break

                await ws_callback({"type": "battle_thinking", "data": {
                    "agent": agent.name, "phase": "turn", "round": round_num,
                }})
                result = await _llm_call(
                    agent, build_battle_system(agent, survivor_names),
                    build_turn_message(history, agent.name, survivor_names, round_num, agent.config.limits),
                )

                if "error" in result:
                    content, err = f"[Erreur : {result['error']}]", True
                else:
                    content, err = result.get("choices", [{}])[0].get("message", {}).get("content", ""), False

                history.append({"agent": agent.name, "phase": "turn", "round": round_num, "content": content})
                await log_callback("info", f"✅ [{agent.name}] tour {round_num}")
                await ws_callback({"type": "battle_turn", "data": {
                    "agent": agent.name, "content": content,
                    "round": round_num, "error": err,
                }})

            if cancelled_flags.get(battle_id):
                break

            # Votes
            is_final = len(survivors) == 2
            await ws_callback({"type": "battle_phase", "data": {
                "phase": "vote", "round": round_num, "survivors": survivor_names,
                "is_final": is_final,
            }})
            vote_map: dict[str, str | None] = {}

            for agent in list(survivors):
                if cancelled_flags.get(battle_id):
                    break

                # En duel final, l'agent peut voter pour lui-même (match nul)
                candidates = survivor_names if is_final else [n for n in survivor_names if n != agent.name]
                await ws_callback({"type": "battle_thinking", "data": {
                    "agent": agent.name, "phase": "vote", "round": round_num,
                }})
                result = await _llm_call(
                    agent, build_battle_system(agent, survivor_names),
                    build_vote_message(history, agent.name, survivor_names, round_num, agent.config.limits, is_final),
                    temperature=0.4,
                )

                if "error" in result:
                    others = [n for n in survivor_names if n != agent.name]
                    target = random.choice(others) if others else None
                    reason = result["error"]
                else:
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    others  = [n for n in survivor_names if n != agent.name]
                    target  = parse_vote(content, candidates) or (random.choice(others) if others else None)
                    reason  = content

                vote_map[agent.name] = target
                await log_callback("info", f"🗳️ [{agent.name}] → {target}")
                await ws_callback({"type": "battle_vote", "data": {
                    "agent": agent.name, "target": target, "reason": reason,
                }})

            if cancelled_flags.get(battle_id):
                break

            # Duel final : vérifier si tout le monde a voté pour soi-même (match nul)
            if is_final:
                self_voters = [voter for voter, target in vote_map.items() if voter == target]
                if len(self_voters) == len(survivors):
                    draw_occurred = True
                    await log_callback("info", "🤝 Match nul — les deux agents ont choisi la collaboration !")
                    await ws_callback({"type": "battle_draw", "data": {
                        "survivors": survivor_names, "round": round_num,
                    }})
                    break

            # Élimination normale
            eliminated, tally, was_random = resolve_votes(vote_map, survivor_names)
            survivors = [a for a in survivors if a.name != eliminated]
            survivor_names = [a.name for a in survivors]

            # Injecter l'annonce dans l'historique pour que les agents ne réfèrent plus à l'éliminé
            history.append({
                "agent":   "SYSTÈME",
                "phase":   "elimination",
                "content": (
                    f"⚠️ {eliminated} a été éliminé et quitte le Battle Royale. "
                    f"Survivants restants : {', '.join(survivor_names)}. "
                    f"Ne faites plus référence à {eliminated} comme participant actif."
                ),
            })

            await log_callback("info", f"💀 [{eliminated}] éliminé{'  (aléatoire)' if was_random else ''}")
            await ws_callback({"type": "battle_elimination", "data": {
                "eliminated": eliminated,
                "tally":      tally,
                "random":     was_random,
                "survivors":  survivor_names,
                "round":      round_num,
            }})

        # Gagnant
        if survivors and not cancelled_flags.get(battle_id):
            winner = survivors[0].name
            await log_callback("info", f"🏆 [{winner}] remporte le Battle Royale !")
            await ws_callback({"type": "battle_winner", "data": {"winner": winner}})

    except Exception as e:
        await log_callback("error", f"❌ Erreur Battle : {e}")

    finally:
        cancelled_flags.pop(battle_id, None)
        await ws_callback({"type": "battle_done", "data": {
            "rounds": round_num,
            "winner": survivors[0].name if len(survivors) == 1 else None,
            "draw":   [a.name for a in survivors] if draw_occurred else None,
        }})
