"""
rag_engine.py
=============
RAG = Retrieval-Augmented Generation

Concept : plutôt que de tout mettre dans le contexte (impossible),
on indexe les documents et on injecte uniquement les passages pertinents.

Pipeline :
1. Indexation : découper les docs en chunks + générer embeddings
2. Recherche   : trouver les chunks les plus similaires à la question
3. Injection   : passer ces chunks au context manager

Technologies utilisées :
- ChromaDB    : base de données vectorielle locale
- sentence-transformers : modèle d'embedding léger et local
"""

import hashlib
from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

CHUNK_SIZE    = 300   # Taille d'un chunk en mots
CHUNK_OVERLAP = 50    # Chevauchement entre chunks (pour éviter de couper le sens)
TOP_K         = 5     # Nombre max de chunks à retourner


class RAGEngine:
    """
    Moteur RAG partagé entre tous les agents.
    Une seule instance est créée au démarrage, pointant vers knowledge/ à la racine.
    """

    def __init__(self, name: str, knowledge_path: Path):
        self.name           = name
        self.knowledge_path = knowledge_path
        self.available      = True
        self._client        = None
        self._collection    = None
        self._embedder      = None
        self._init_chromadb()

    def _init_chromadb(self):
        """Initialise ChromaDB avec un répertoire de persistance local."""
        db_path = self.knowledge_path.parent / ".chromadb"
        db_path.mkdir(exist_ok=True)

        self._client = chromadb.PersistentClient(
            path=str(db_path),
            settings=Settings(anonymized_telemetry=False)
        )
        self._collection = self._client.get_or_create_collection(
            name=f"kb_{self.name}",
            metadata={"hnsw:space": "cosine"}
        )
        # Modèle léger — tourne sur CPU sans GPU
        self._embedder = SentenceTransformer("all-MiniLM-L6-v2")

    def index_file(self, file_path: Path) -> dict:
        """Indexe un seul fichier. Appelé après write_knowledge pour une indexation immédiate."""
        if file_path.suffix not in [".txt", ".md", ".rst"]:
            return {"indexed": 0, "chunks": 0}

        content = file_path.read_text(encoding="utf-8", errors="ignore")
        chunks  = self._split_into_chunks(content)
        if not chunks:
            return {"indexed": 0, "chunks": 0}

        ids        = [self._chunk_id(file_path.name, i, c) for i, c in enumerate(chunks)]
        embeddings = self._embedder.encode(chunks).tolist()
        metadatas  = [{"source": file_path.name, "chunk_index": i} for i in range(len(chunks))]

        self._collection.upsert(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas)
        return {"indexed": 1, "chunks": len(chunks)}

    def index_knowledge(self) -> dict:
        """
        Indexe tous les fichiers du dossier knowledge/.
        Retourne des stats sur l'indexation.
        """
        if not self.knowledge_path.exists():
            return {"indexed": 0, "chunks": 0}

        indexed_files = 0
        total_chunks  = 0

        for file_path in self.knowledge_path.rglob("*"):
            if file_path.suffix not in [".txt", ".md", ".rst"]:
                continue

            content = file_path.read_text(encoding="utf-8", errors="ignore")
            chunks  = self._split_into_chunks(content)

            if not chunks:
                continue

            ids        = [self._chunk_id(file_path.name, i, c) for i, c in enumerate(chunks)]
            embeddings = self._embedder.encode(chunks).tolist()
            metadatas  = [{"source": file_path.name, "chunk_index": i} for i in range(len(chunks))]

            # Upsert : met à jour si déjà présent, crée sinon
            self._collection.upsert(
                ids=ids,
                documents=chunks,
                embeddings=embeddings,
                metadatas=metadatas,
            )

            indexed_files += 1
            total_chunks  += len(chunks)

        return {"indexed": indexed_files, "chunks": total_chunks}

    def search(self, query: str, n_results: int = TOP_K) -> list[dict]:
        """
        Recherche les chunks les plus pertinents pour une query.
        Retourne une liste de chunks triés par pertinence décroissante.
        """
        if self._collection is None:
            return []

        count = self._collection.count()
        if count == 0:
            return []

        n_results = min(n_results, count)
        query_embedding = self._embedder.encode([query]).tolist()

        results = self._collection.query(
            query_embeddings=query_embedding,
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        chunks = []
        for i, doc in enumerate(results["documents"][0]):
            distance  = results["distances"][0][i]
            relevance = round(1 - distance, 3)
            chunks.append({
                "text":      doc,
                "source":    results["metadatas"][0][i].get("source", "?"),
                "relevance": relevance,
            })

        return [c for c in chunks if c["relevance"] > 0.3]

    def _split_into_chunks(self, text: str) -> list[str]:
        """
        Découpe un texte en chunks avec chevauchement.
        Stratégie simple : par mots (suffisant pour usage pédagogique).
        """
        words  = text.split()
        chunks = []
        start  = 0

        while start < len(words):
            end   = min(start + CHUNK_SIZE, len(words))
            chunk = " ".join(words[start:end])
            if chunk.strip():
                chunks.append(chunk)
            start += CHUNK_SIZE - CHUNK_OVERLAP

        return chunks

    def _chunk_id(self, filename: str, index: int, content: str) -> str:
        """Génère un ID unique et déterministe pour un chunk."""
        key = f"{filename}:{index}:{content[:50]}"
        return hashlib.md5(key.encode()).hexdigest()

    def get_status(self) -> dict:
        """Retourne le statut du RAG pour l'interface."""
        count = self._collection.count() if self._collection else 0
        return {"available": True, "count": count}
