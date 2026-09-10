"""Incremental exact cosine cache populated only through the collection API."""
import numpy as np


class VectorCache:
    def __init__(self, dimensions):
        self.dimensions = dimensions
        self.ids = []
        self.positions = {}
        self.matrix = np.empty((0, dimensions), dtype=np.float32)
        self.norms = np.empty(0, dtype=np.float32)
        self.loaded = False

    def reserve(self, count):
        if count <= len(self.matrix):
            return
        capacity = max(128, count + count // 8)
        matrix = np.empty((capacity, self.dimensions), dtype=np.float32)
        norms = np.empty(capacity, dtype=np.float32)
        if self.ids:
            matrix[:len(self.ids)] = self.matrix[:len(self.ids)]
            norms[:len(self.ids)] = self.norms[:len(self.ids)]
        self.matrix, self.norms = matrix, norms

    def upsert(self, ids, embeddings):
        self.reserve(len(self.ids) + sum(did not in self.positions for did in ids))
        for did, embedding in zip(ids, embeddings):
            if did not in self.positions:
                self.positions[did] = len(self.ids)
                self.ids.append(did)
            pos = self.positions[did]
            vector = np.asarray(embedding, dtype=np.float32)
            self.matrix[pos] = vector
            # Match MemPalace's float32, per-row norm calculation.
            self.norms[pos] = np.sqrt(np.sum(vector * vector))

    def delete(self, ids):
        for did in ids:
            pos = self.positions.pop(did, None)
            if pos is not None:
                self.ids[pos] = None

    def load(self, collection):
        self.loaded = False
        self.ids, self.positions = [], {}
        self.matrix = np.empty((0, self.dimensions), dtype=np.float32)
        self.norms = np.empty(0, dtype=np.float32)
        ids = collection.get(include=[])['ids']
        self.reserve(len(ids))
        # Explicit embeddings_out is a supported collection capability. Bounded
        # pages avoid materializing the corpus as millions of Python floats.
        for offset in range(0, len(ids), 128):
            batch = collection.get(ids=ids[offset:offset + 128], include=['embeddings'])
            self.upsert(batch['ids'], batch['embeddings'])
        self.loaded = True

    def query(self, vector, eligible, limit=30):
        if not self.ids:
            return []
        q = np.asarray(vector, dtype=np.float32)
        if q.shape != (self.dimensions,):
            raise ValueError('Query embedding dimension mismatch')
        count = len(self.ids)
        denom = self.norms[:count] * float(np.linalg.norm(q))
        dots = self.matrix[:count] @ q
        cosine = np.zeros(dots.shape, dtype=np.float32)
        np.divide(dots, denom, out=cosine, where=denom > 0)
        np.clip(cosine, -1., 1., out=cosine)
        # Filter before limiting, preserving native row order for tied distances.
        order = np.argsort(1. - cosine, kind='mergesort')
        result = []
        for pos in order:
            did = self.ids[int(pos)]
            if did in eligible:
                result.append(did)
                if len(result) == limit:
                    break
        return result
