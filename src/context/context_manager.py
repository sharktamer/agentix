"""
context_manager.py
==================
Le Context Manager est le composant central de tout système agentique.

Son rôle : construire le prompt final en respectant les limites de tokens.
Chaque agent possède ses propres limites (ContextLimits) définies dans config.json.
"""

import tiktoken

# Encodeur de tokens (cl100k_base est proche de la plupart des LLMs modernes)
_enc = tiktoken.get_encoding("cl100k_base")


class ContextLimits:
    """
    Limites de tokens configurables.
    Une instance globale `DEFAULT_LIMITS` est utilisée par défaut.
    L'UI peut lire et modifier ces valeurs via l'API.
    """
    def __init__(
        self,
        total:   int = 3000,
        system:  int = 600,
        history: int = 1000,
        rag:     int = 800,
        tools:   int = 300,
        user:    int = 300,
    ):
        self.total   = total
        self.system  = system
        self.history = history
        self.rag     = rag
        self.tools   = tools
        self.user    = user

    def to_dict(self) -> dict:
        return {
            "total":   self.total,
            "system":  self.system,
            "history": self.history,
            "rag":     self.rag,
            "tools":   self.tools,
            "user":    self.user,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ContextLimits":
        return cls(
            total   = int(d.get("total",   3000)),
            system  = int(d.get("system",  600)),
            history = int(d.get("history", 1000)),
            rag     = int(d.get("rag",     800)),
            tools   = int(d.get("tools",   300)),
            user    = int(d.get("user",    300)),
        )


DEFAULT_LIMITS = ContextLimits()


def count_tokens(text: str) -> int:
    """Compte le nombre de tokens dans un texte."""
    return len(_enc.encode(text))


def count_messages_tokens(messages: list) -> int:
    """Compte les tokens d'une liste de messages."""
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        total += count_tokens(content)
        total += 4  # overhead par message (role, séparateurs)
    return total


def trim_history(history: list, max_tokens: int) -> tuple:
    """
    Réduit l'historique pour respecter la limite de tokens.
    Stratégie : conserver les messages les plus récents.
    """
    if count_messages_tokens(history) <= max_tokens:
        return history, False

    trimmed = list(history)
    while trimmed and count_messages_tokens(trimmed) > max_tokens:
        trimmed.pop(0)

    return trimmed, True


def select_rag_chunks(chunks: list, max_tokens: int) -> tuple:
    """
    Sélectionne les chunks RAG les plus pertinents dans la limite de tokens.
    Les chunks sont déjà triés par score de pertinence.
    """
    total_found = len(chunks)
    selected    = []
    used_tokens = 0

    for chunk in chunks:
        chunk_text   = chunk.get("text", "")
        chunk_tokens = count_tokens(chunk_text)
        if used_tokens + chunk_tokens <= max_tokens:
            selected.append(chunk)
            used_tokens += chunk_tokens
        else:
            break

    return selected, total_found


def build_context(
    system_prompt:     str,
    history:           list,
    rag_chunks:        list,
    tools_description: str,
    user_message:      str,
    limits:            ContextLimits = None,
) -> dict:
    """
    Construit le contexte final en respectant les limites de tokens.

    Retourne :
    - messages        : liste de messages pour l'API LLM
    - token_breakdown : répartition des tokens + limites courantes
    - logs            : logs pédagogiques sur les décisions
    - was_trimmed     : si des éléments ont été réduits
    """
    L = limits or DEFAULT_LIMITS
    logs        = []
    was_trimmed = False

    # ── 1. System prompt ──────────────────────────────────────────────────────
    system_tokens = count_tokens(system_prompt)
    if system_tokens > L.system:
        system_prompt = _truncate_text(system_prompt, L.system)
        system_tokens = count_tokens(system_prompt)
        logs.append("⚠️  System prompt tronqué (trop long)")
        was_trimmed = True

    # ── 2. User input ─────────────────────────────────────────────────────────
    user_tokens = count_tokens(user_message)
    if user_tokens > L.user:
        user_message = _truncate_text(user_message, L.user)
        user_tokens  = count_tokens(user_message)
        logs.append("⚠️  Message utilisateur tronqué")
        was_trimmed = True

    # ── 3. Tools ──────────────────────────────────────────────────────────────
    tools_tokens = count_tokens(tools_description) if tools_description else 0

    # ── 4. Historique ─────────────────────────────────────────────────────────
    trimmed_history, history_was_trimmed = trim_history(history, L.history)
    history_tokens = count_messages_tokens(trimmed_history)

    if history_was_trimmed:
        removed = len(history) - len(trimmed_history)
        logs.append(f"📝 Historique trop long → {removed} message(s) ancien(s) retiré(s)")
        was_trimmed = True

    # ── 5. RAG ────────────────────────────────────────────────────────────────
    selected_chunks, total_chunks = select_rag_chunks(rag_chunks, L.rag)
    rag_tokens = sum(count_tokens(c.get("text", "")) for c in selected_chunks)

    if total_chunks > len(selected_chunks):
        logs.append(f"🔍 RAG : {total_chunks} chunks → {len(selected_chunks)} conservés (limite tokens)")
        was_trimmed = True
    elif total_chunks > 0:
        logs.append(f"🔍 RAG : {total_chunks} chunk(s) injecté(s)")

    # ── 6. Assemblage du system prompt final ──────────────────────────────────
    final_system = system_prompt
    if tools_description:
        final_system += f"\n\n## Outils disponibles\n{tools_description}"
    if selected_chunks:
        rag_text = "\n\n".join(c.get("text", "") for c in selected_chunks)
        final_system += f"\n\n## Contexte documentaire pertinent\n{rag_text}"

    # ── 7. Construction des messages ──────────────────────────────────────────
    messages = [{"role": "system", "content": final_system}]
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": user_message})

    # ── 8. Calcul du total ────────────────────────────────────────────────────
    total_tokens = system_tokens + history_tokens + rag_tokens + tools_tokens + user_tokens

    token_breakdown = {
        "system":    system_tokens,
        "history":   history_tokens,
        "rag":       rag_tokens,
        "tools":     tools_tokens,
        "user":      user_tokens,
        "total":     total_tokens,
        "max":       L.total,
        "percent":   round((total_tokens / L.total) * 100) if L.total else 0,
        # Limites individuelles — pour que l'UI sache quoi afficher
        "limits":    L.to_dict(),
    }

    return {
        "messages":        messages,
        "token_breakdown": token_breakdown,
        "logs":            logs,
        "was_trimmed":     was_trimmed,
    }


def _truncate_text(text: str, max_tokens: int) -> str:
    """Tronque un texte pour respecter une limite de tokens."""
    tokens = _enc.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return _enc.decode(tokens[:max_tokens]) + "... [tronqué]"
