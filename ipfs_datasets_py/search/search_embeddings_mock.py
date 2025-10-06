"""Mock search_embeddings module for testing when dependencies are unavailable."""

class search_embeddings:
    """Mock search_embeddings class for testing when dependencies unavailable"""
    def __init__(self, *args, **kwargs):
        pass
    
    async def search(self, *args, **kwargs):
        return {'results': [], 'status': 'mock'}
    
    async def generate_embeddings(self, *args, **kwargs):
        return []