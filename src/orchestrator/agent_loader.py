"""
agent_loader.py
===============
Charge et parse les définitions d'agents depuis les fichiers.

Structure d'un agent :
    agents/
        mon_agent/
            agent.md     ← définition en texte clair
            config.json  ← config LM Studio + tools autorisés + permissions spawn
            memory/      ← workspace privé persistant (write_file / read_file)
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from context.context_manager import ContextLimits

# Liste de tous les tools existants dans le système
ALL_TOOLS = [
    "read_file", "write_file", "list_directory",
    "search_knowledge", "write_knowledge",
    "spawn_agent",
    "ssh_exec", "ssh_read_file", "process_status", "process_wait",
]


@dataclass
class AgentConfig:
    """Configuration d'un agent."""
    provider_id:    str           = ""
    model:          str           = ""
    temperature:    float         = 0.7
    max_tokens:     int           = 512
    allowed_tools:     list          = field(default_factory=lambda: ["read_file", "write_file", "list_directory", "search_knowledge"])
    can_spawn:         bool          = False
    spawnable_agents:  list          = field(default_factory=list)
    max_iterations:    int           = 5
    limits:            ContextLimits = field(default_factory=ContextLimits)
    tags:              list          = field(default_factory=list)
    in_salon:          bool          = False
    in_battle:         bool          = False


@dataclass
class Agent:
    """Représentation complète d'un agent chargé."""
    name:          str
    path:          Path
    system_prompt: str
    config:        AgentConfig
    raw_markdown:  str
    metadata:      dict = field(default_factory=dict)

    @property
    def memory_path(self):
        return self.path / "memory"


def load_agent(agent_path):
    agent_md    = agent_path / "agent.md"
    config_file = agent_path / "config.json"

    if not agent_md.exists():
        return None

    raw_markdown  = agent_md.read_text(encoding="utf-8")
    metadata      = _parse_sections(raw_markdown)
    system_prompt = _build_system_prompt(metadata)
    config        = _load_config(config_file)

    return Agent(
        name          = agent_path.name,
        path          = agent_path,
        system_prompt = system_prompt,
        config        = config,
        raw_markdown  = raw_markdown,
        metadata      = metadata,
    )


def discover_agents(agents_dir):
    agents = []
    if not agents_dir.exists():
        return agents
    for entry in sorted(agents_dir.iterdir()):
        if entry.is_dir():
            agent = load_agent(entry)
            if agent:
                agents.append(agent)
    return agents


def save_agent_markdown(agent_path, content):
    """Sauvegarde le markdown d'un agent (appelé par l'éditeur UI)."""
    (agent_path / "agent.md").write_text(content, encoding="utf-8")


def save_agent_config(agent_path, config_data):
    """Sauvegarde la config JSON d'un agent (appelé par l'éditeur UI)."""
    (agent_path / "config.json").write_text(
        json.dumps(config_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def create_agent(agents_dir, agent_name):
    """Crée un nouveau dossier d'agent avec des fichiers par défaut."""
    agent_path = agents_dir / agent_name
    agent_path.mkdir(parents=True, exist_ok=True)
    (agent_path / "memory").mkdir(exist_ok=True)

    default_md = f"""# Nom
{agent_name}

# Role
Décris le rôle de cet agent ici.

# Personnalité
Décris la personnalité ici.

# Objectif
Décris l'objectif principal ici.

# Capacités
- Capacité 1
- Capacité 2

# Contraintes
- Contrainte 1
"""
    default_config = {
        "provider_id":       "",
        "model":             "",
        "temperature":       0.7,
        "max_tokens":        512,
        "allowed_tools":     ["read_file", "list_directory", "search_knowledge"],
        "can_spawn":         False,
        "spawnable_agents":  [],
        "max_iterations":    5,
        "tags":              [],
        "in_salon":          False,
        "in_battle":         False,
        "context_limits": {
            "total": 3000, "system": 600, "history": 1000,
            "rag": 800, "tools": 300, "user": 300,
        },
    }

    (agent_path / "agent.md").write_text(default_md, encoding="utf-8")
    (agent_path / "config.json").write_text(
        json.dumps(default_config, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    return agent_path


def _parse_sections(markdown):
    sections        = {}
    current_section = None
    lines           = []

    for line in markdown.splitlines():
        if line.startswith("# "):
            if current_section:
                sections[current_section] = "\n".join(lines).strip()
            current_section = line[2:].strip().lower()
            lines           = []
        else:
            if current_section:
                lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(lines).strip()

    return sections


def _build_system_prompt(metadata):
    parts = []

    name = metadata.get("nom", metadata.get("name", "Agent"))
    role = metadata.get("role", "Assistant IA")
    parts.append(f"Tu es {name}. {role}")

    if personality := metadata.get("personnalité", metadata.get("personalite", "")):
        parts.append(f"\nPersonnalité : {personality}")

    if objective := metadata.get("objectif", ""):
        parts.append(f"\nObjectif principal : {objective}")

    if capabilities := metadata.get("capacités", metadata.get("capacites", "")):
        parts.append(f"\nTes capacités :\n{capabilities}")

    if constraints := metadata.get("contraintes", ""):
        parts.append(f"\nContraintes importantes :\n{constraints}")

    return "\n".join(parts)


def _load_config(config_file):
    if not config_file.exists():
        return AgentConfig()

    try:
        data      = json.loads(config_file.read_text(encoding="utf-8"))
        raw_tools = data.get("allowed_tools", None)

        if raw_tools is None:
            allowed = ["read_file", "write_file", "list_directory", "search_knowledge"]
        else:
            allowed = [t for t in raw_tools if t in ALL_TOOLS]

        can_spawn = data.get("can_spawn", False)

        if can_spawn and "spawn_agent" not in allowed:
            allowed.append("spawn_agent")
        elif not can_spawn and "spawn_agent" in allowed:
            allowed.remove("spawn_agent")

        ld = data.get("context_limits", {})
        limits = ContextLimits(
            total   = int(ld.get("total",   3000)),
            system  = int(ld.get("system",  600)),
            history = int(ld.get("history", 1000)),
            rag     = int(ld.get("rag",     800)),
            tools   = int(ld.get("tools",   300)),
            user    = int(ld.get("user",    300)),
        )

        return AgentConfig(
            provider_id       = data.get("provider_id", ""),
            model             = data.get("model", ""),
            temperature       = float(data.get("temperature", 0.7)),
            max_tokens        = int(data.get("max_tokens", 512)),
            allowed_tools     = allowed,
            can_spawn         = can_spawn,
            spawnable_agents  = data.get("spawnable_agents", []),
            max_iterations    = int(data.get("max_iterations", 5)),
            limits            = limits,
            tags              = data.get("tags", []),
            in_salon          = bool(data.get("in_salon", False)),
            in_battle         = bool(data.get("in_battle", False)),
        )
    except (json.JSONDecodeError, ValueError):
        return AgentConfig()
