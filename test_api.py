import asyncio
from src.api.main import predict_batch, MatchBatchRequest
request = MatchBatchRequest(match_ids=[540612])
print("Starting predict batch...")
results = predict_batch(request)
print("Results:", results)
