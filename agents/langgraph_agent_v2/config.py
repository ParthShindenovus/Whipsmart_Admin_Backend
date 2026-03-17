"""
Configuration for LangGraph Agent V2.
"""
from django.conf import settings

# LLM Configuration
LLM_TEMPERATURE_RESPONSE = 0.7
LLM_TEMPERATURE_REASONING = 0.5
LLM_TEMPERATURE_VALIDATION = 0.3
LLM_MAX_TOKENS_RESPONSE = 2000
LLM_MAX_TOKENS_REASONING = 1000
LLM_MAX_TOKENS_VALIDATION = 500

# Conversation History
CONVERSATION_HISTORY_LIMIT = 4
EXTENDED_HISTORY_LIMIT = 10

# Name Collection
NAME_COLLECTION_THRESHOLD = 3  # Ask for name after 3 questions

# Team Connection
TEAM_CONNECTION_THRESHOLD = 3  # Start offering team connection after 3 questions

# Parallel Processing
MAX_PARALLEL_WORKERS = 3  # Max workers for ThreadPoolExecutor

# Validation
MAX_VALIDATION_RETRIES = 2  # Max retries if validation fails
VALIDATION_CONFIDENCE_THRESHOLD = 0.8  # Minimum confidence for validation

# RAG Configuration
RAG_TOP_K = 5  # Number of results to retrieve
RAG_MIN_SCORE = 0.7  # Minimum relevance score

# RAG Query Variations (cost vs recall tradeoff)
# If enabled, the agent will issue multiple Pinecone searches per user question.
ENABLE_RAG_QUERY_VARIATIONS_DOMAIN = False
ENABLE_RAG_QUERY_VARIATIONS_SERVICE_DISCOVERY = False
MAX_RAG_QUERY_VARIATIONS = 3  # cap extra queries (in addition to base query)

# Response Timeouts
RESPONSE_TIMEOUT = 30  # Seconds
TOOL_TIMEOUT = 10  # Seconds

# Caching
ENABLE_CACHING = True
CACHE_TTL = 3600  # 1 hour
