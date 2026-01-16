# Vespa vs Elasticsearch: Architecture & Implementation Comparison

This document provides a concise comparison of **Vespa** and **Elasticsearch** implementations in Onyx, focusing on architectural differences, schema definitions, implementation patterns, and feature gaps.

---

## 1. Architecture & Deployment

### Vespa: Docker-Based Deployment

**Deployment Model:**
- **Local:** Docker container (`vespaengine/vespa`) with application package deployment
- **Cloud:** Vespa Cloud (SaaS) with certificate-based authentication
- **Configuration:** Jinja templates (`.xml.jinja`, `.sd.jinja`) rendered at deployment time
- **Deployment Process:** 
  1. Render Jinja templates with variables (embedding dimensions, multi-tenant flags)
  2. Build application package (ZIP file)
  3. POST to `/application/v2/tenant/default/prepareandactivate`
  4. Schema validated before deployment (prevents invalid configurations)

**Key Characteristics:**
- Schema-first approach with deployment-time validation
- Application package contains all schemas and services configuration
- Schema changes require full redeployment
- Strong type safety and governance

**Files:**
- `backend/onyx/document_index/vespa/app_config/services.xml.jinja` - Container topology
- `backend/onyx/document_index/vespa/app_config/schemas/danswer_chunk.sd.jinja` - Document schema
- `backend/onyx/document_index/vespa/app_config/validation-overrides.xml.jinja` - Schema evolution rules

### Elasticsearch: Cloud or Self-Hosted

**Deployment Model:**
- **Cloud:** Elastic Cloud (SaaS) with API key authentication
- **Self-hosted:** Standard Docker image or Kubernetes deployment
- **Configuration:** Python dictionaries converted to JSON mappings
- **Deployment Process:**
  1. Call `PUT /{index_name}` with mappings and settings
  2. No application package required
  3. Schema validation occurs at indexing time (runtime errors)

**Key Characteristics:**
- Code-defined schemas with runtime validation
- Incremental schema updates (add fields without redeployment)
- Flexible but less safe (errors discovered at runtime)
- Simple REST API for index management

**Files:**
- `backend/eleven/onyx/document_index/elasticsearch/schema.py` - Schema definition class
- `ElasticsearchSchema.get_document_schema()` - Returns mapping dictionary

---

## 2. Schema Differences

### Vespa: Jinja-Templated Schema Files

**Format:** `.sd.jinja` files (Vespa Schema Definition)

**Key Features:**
- **Conditional Fields:** Multi-tenant support via Jinja conditionals
  ```vespa
  {% if multi_tenant %}
  field tenant_id type string {
      indexing: summary | attribute
      rank: filter
      attribute: fast-search
  }
  {% endif %}
  ```
- **Knowledge Graph Fields:** Native support with structured relationships
  ```vespa
  struct kg_relationship {
      field source type string {}
      field rel_type type string {}
      field target type string {}
  }
  field kg_entities type array<string> {
      attribute: fast-search
  }
  field kg_relationships type array<kg_relationship> { ... }
  ```
- **Ranking Profiles:** Declarative ranking expressions in schema
  ```vespa
  rank-profile hybrid_search_semantic_base_768 {
      global-phase {
          expression {
              (query(alpha) * vector_score + (1 - query(alpha)) * bm25_score)
              * document_boost * recency_bias
          }
          rerank-count: 1000
      }
  }
  ```
- **Tensor Fields:** Support for multi-dimensional embeddings (mini-chunks)
  ```vespa
  field embeddings type tensor<float>(t{},x[768]) {
      attribute { distance-metric: angular }
  }
  ```

**Location:** `backend/onyx/document_index/vespa/app_config/schemas/danswer_chunk.sd.jinja`

### Elasticsearch: Python Dictionary Mappings

**Format:** Python dictionaries returned by `get_document_schema()`

**Key Features:**
- **Static Schema:** No conditional rendering (tenant_id removed if not multitenant)
  ```python
  if not multitenant:
      mappings["properties"].pop(TENANT_ID, None)
  ```
- **No Knowledge Graph:** No native KG fields in schema
- **No Ranking Profiles:** Ranking logic in application code (RRF parameters)
- **Single Vector Field:** `dense_vector` type supports one vector per field
  ```python
  EMBEDDINGS: {
      "type": "dense_vector",
      "dims": vector_dimension,
      "similarity": "cosine",
  }
  ```
- **Nested ACL:** Access control via nested mappings
  ```python
  ACCESS_CONTROL_LIST: {
      "type": "nested",
      "properties": {
          "value": {"type": "keyword"},
          "weight": {"type": "integer"},
      },
  }
  ```

**Location:** `backend/eleven/onyx/document_index/elasticsearch/schema.py:93`

### Schema Comparison Summary

| Aspect | Vespa | Elasticsearch |
|--------|-------|---------------|
| **Format** | Jinja templates (`.sd.jinja`) | Python dictionaries |
| **Validation** | Deployment-time (prevents invalid schemas) | Runtime (errors at indexing) |
| **Multi-tenant** | Conditional field via `{% if multi_tenant %}` | Field removed if not multitenant |
| **Knowledge Graph** | ✅ Native fields (`kg_entities`, `kg_relationships`) | ❌ Not implemented |
| **Ranking Profiles** | ✅ Declarative in schema | ❌ Application-level (RRF) |
| **Mini-chunks** | ✅ Tensor with multiple dimensions | ❌ Single vector only |
| **Schema Evolution** | Validation overrides (time-bounded) | Incremental field additions |

---

## 3. Implementation Differences

### 3.1 Indexing Strategy

#### Vespa: Parallel HTTP PUT Requests

**Approach:**
- Uses `httpx.Client` (HTTP/2 support) for individual requests
- **No bulk API** - Vespa doesn't support native bulk operations
- **Parallelization:** `ThreadPoolExecutor` with 32 threads
- Each document indexed via separate HTTP PUT request
- Batch size: 128 documents processed in parallel

**Code:**
```python
# backend/onyx/document_index/vespa/indexing_utils.py
def batch_index_vespa_chunks(...):
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=32)
    chunk_index_future = {
        executor.submit(_index_vespa_chunk, chunk, index_name, http_client, multitenant): chunk
        for chunk in chunks
    }
```

**Performance:**
- Better for high-throughput scenarios with many small documents
- HTTP/2 multiplexing reduces connection overhead
- Parallel execution maximizes network utilization

#### Elasticsearch: Sequential Bulk API

**Approach:**
- Uses `Elasticsearch` Python client
- **Native bulk API:** `bulk()` helper indexes multiple documents in single request
- **Sequential:** Batch-by-batch processing (no client-level parallelization)
- Batch size: 500 documents per bulk request

**Code:**
```python
# backend/eleven/onyx/document_index/elasticsearch/indexing_utils.py
def batch_index_elasticsearch_chunks(...):
    bulk_actions = [{"_op_type": "index", "_index": index_name, ...} for chunk in chunks]
    success, errors = bulk(client=es_client, actions=bulk_actions, ...)
```

**Performance:**
- Better for large batches of documents
- Single bulk request reduces HTTP overhead
- Sequential processing can be bottleneck for high-volume indexing

### 3.2 Hybrid Retrieval Implementation

#### Vespa: YQL with Declarative Ranking

**Query Language:** YQL (Yahoo Query Language) - single string

**Query Construction:**
```python
# backend/onyx/document_index/vespa/vespa_document_index.py:650
yql = (
    YQL_BASE.format(index_name=self._index_name)
    + vespa_where_clauses  # Filters
    + f"(({{targetHits: {target_hits}}}nearestNeighbor(embeddings, query_embedding)) "
    + f"or ({{targetHits: {target_hits}}}nearestNeighbor(title_embedding, query_embedding)) "
    + 'or ({grammar: "weakAnd"}userInput(@query)) '  # Keyword search
    + f'or ({{defaultIndex: "{CONTENT_SUMMARY}"}}userInput(@query)))'
)
```

**Ranking:**
- **Multi-phase ranking:** First-phase (vector only) → Global-phase (hybrid)
- **Ranking profile:** Selected from schema (`hybrid_search_semantic_base_768`)
- **Alpha control:** Direct parameter (0.2 for KEYWORD, 0.5 for SEMANTIC)
- **Title/Content ratio:** Applied to both vector and keyword components
- **Additional factors:** Native support for document boost, recency bias, aggregated chunk boost

**Key Features:**
- Searches both `embeddings` and `title_embedding` separately
- `targetHits` controls candidate pool before reranking (min 1000)
- Ranking expression defined in schema, not application code

#### Elasticsearch: Query DSL with RRF

**Query Language:** Query DSL (JSON objects)

**Query Construction:**
```python
# backend/eleven/onyx/document_index/elasticsearch/index.py:520
# Text query (BM25)
text_query = {
    "multi_match": {
        "query": final_query,
        "fields": [
            f"semantic_identifier^{title_boost * text_match_boost}",
            f"content^{content_boost * text_match_boost}",
        ],
        "type": "best_fields",
    }
}

# Vector query (KNN) - separate parameter
params["knn"] = {
    "field": "embeddings",
    "query_vector": query_embedding,
    "k": num_to_retrieve,
    "num_candidates": effective_num_candidates,  # 10000 for SEMANTIC
    "filter": {"bool": {"must": filter_clauses}},
}

# RRF combination
params["rank"] = {
    "rrf": {
        "window_size": num_to_retrieve * 2,
        "rank_constant": rrf_rank_constant,  # 20 for KEYWORD, 60 for SEMANTIC
    }
}
```

**Ranking:**
- **Single-phase ranking:** Both text and vector search executed, then combined
- **RRF (Reciprocal Rank Fusion):** Merges separate result sets
- **Alpha handling:** Indirect via `text_match_boost` and `num_candidates`
- **Title/Content ratio:** Only affects keyword search (no title vector search)
- **Additional factors:** Requires `function_score` wrapper or post-processing

**Key Features:**
- Only searches `embeddings` field (title embedding not used in vector search)
- `num_candidates` controls vector search breadth
- Ranking logic in application code, not schema

### 3.3 Retrieval API Comparison

| Feature | Vespa | Elasticsearch |
|---------|-------|---------------|
| **APIs** | Visit API + Search API | Single Search API |
| **Parallelization** | ✅ Parallel Visit API retrieval | ❌ Sequential loops |
| **Chunk Filtering** | ✅ Query-level (YQL) | ❌ Post-retrieval Python filtering |
| **Pagination** | ✅ Continuation tokens | ❌ Offset-based (slow for deep pages) |
| **Intelligent Routing** | ✅ Auto Visit vs Search API | ❌ Manual batch management |

---

## 4. Feature Differences

### 4.1 Multi-Tenancy

#### Vespa: Native Schema-Level Support

**Implementation:**
- `tenant_id` field conditionally included in schema via Jinja template
- Field has `fast-search` attribute for efficient filtering
- Multi-tenant indices registered via `register_multitenant_indices()` method
- Tenant isolation enforced at query level (YQL filters)

**Code:**
```python
# backend/onyx/document_index/vespa/index.py:369
def register_multitenant_indices(...):
    # Renders Jinja templates with multi_tenant=True
    # Creates application package with all schemas
    # Deploys to Vespa
```

**Location:** `backend/onyx/document_index/vespa/app_config/schemas/danswer_chunk.sd.jinja:10-16`

#### Elasticsearch: Application-Level Only

**Implementation:**
- `tenant_id` field exists in mappings but not enforced by platform
- Application must ensure all queries include `tenant_id` filter
- No native multi-tenant index management
- Risk of data leakage if filters are missed

**Options:**
1. Separate indices per tenant (resource intensive)
2. Application-level filtering (error-prone)
3. Index aliases (complex setup)

**Location:** `backend/eleven/onyx/document_index/elasticsearch/schema.py:113`

### 4.2 Knowledge Graph Support

#### Vespa: Native Implementation

**Schema Fields:**
```vespa
field kg_entities type array<string> {
    attribute: fast-search
}
struct kg_relationship {
    field source type string {}
    field rel_type type string {}
    field target type string {}
}
field kg_relationships type array<kg_relationship> {
    struct-field source { attribute: fast-search; }
    struct-field rel_type { attribute: fast-search; }
    struct-field target { attribute: fast-search; }
}
field kg_terms type array<string> {
    attribute: fast-search
}
```

**Usage:**
- Used in `backend/onyx/document_index/vespa/kg_interactions.py`
- KG filters built using YQL `contains` operator
- Efficient relationship queries via `sameElement` operator

**Location:** `backend/onyx/document_index/vespa/app_config/schemas/danswer_chunk.sd.jinja:101-126`

#### Elasticsearch: Not Implemented

**Limitations:**
- ❌ No native KG fields in schema
- Would require:
  - Adding custom fields to mappings
  - Implementing relationship query logic in application code
  - Using nested queries (less efficient than Vespa's `fast-search` attributes)
  - No efficient way to query relationships

---

## 5. OpenSearch: Upcoming Migration

### Migration Status

Onyx is planning to migrate to **OpenSearch** as the primary vector database. The migration is in progress with infrastructure already in place.

**Current State:**
- OpenSearch implementation exists in `backend/onyx/document_index/opensearch/`
- Can be enabled via `ENABLE_OPENSEARCH_FOR_ONYX` environment variable
- Factory pattern supports switching between Vespa and OpenSearch

**Code Location:**
```python
# backend/onyx/document_index/factory.py:31
if ENABLE_OPENSEARCH_FOR_ONYX:
    return OpenSearchOldDocumentIndex(...)
else:
    return VespaIndex(...)
```

### OpenSearch Architecture

**4-Layer Architecture:**

1. **OpenSearchClient** (`client.py`)
   - Pure transport layer (HTTP requests/responses)
   - Connection pooling, retries
   - No business logic

2. **DocumentSchema** (`schema.py`)
   - Pydantic models for validation
   - Defines kNN vector fields with HNSW parameters
   - Schema validation at application level

3. **DocumentQuery** (query construction)
   - Builds OpenSearch query DSL from Onyx query objects
   - Handles query normalization and filter construction

4. **OpenSearchDocumentIndex** (`opensearch_document_index.py`)
   - Business orchestration
   - Converts between Onyx `InferenceChunk` and OpenSearch document format
   - Implements `DocumentIndex` interface

**Key Features:**
- **HNSW Algorithm:** Configurable parameters (`ef_construction`, `ef_search`, `m`)
- **Hybrid Search:** Uses OpenSearch `hybrid` query type
- **Multi-tenant:** Application-level filtering (similar to Elasticsearch)
- **Search Pipelines:** Normalization pipelines (min-max, z-score)

**Limitations:**
- Maximum 10,000 results per query (OpenSearch default)
- No partial document updates (full document replacement required)
- Sequential batch indexing (no parallelization like Vespa)

**Files:**
- `backend/onyx/document_index/opensearch/opensearch_document_index.py` - Main implementation
- `backend/onyx/document_index/opensearch/client.py` - Transport layer
- `backend/onyx/document_index/opensearch/schema.py` - Schema definition

---

## Summary

### Key Architectural Differences

| Aspect | Vespa | Elasticsearch | OpenSearch |
|--------|-------|---------------|------------|
| **Deployment** | Docker + application packages | Cloud or self-hosted | Cloud or self-hosted |
| **Schema** | Jinja templates (deployment-time validation) | Python dicts (runtime validation) | Pydantic models (application validation) |
| **Indexing** | Parallel HTTP PUT (32 threads) | Sequential bulk API | Sequential (TODO: batch support) |
| **Hybrid Search** | YQL + declarative ranking profiles | Query DSL + RRF | Hybrid query type |
| **Multi-tenant** | ✅ Native schema-level | ⚠️ Application-level | ⚠️ Application-level |
| **Knowledge Graph** | ✅ Native fields | ❌ Not implemented | ❌ Not implemented |
| **Ranking** | Multi-phase (first + global) | Single-phase (RRF) | Single-phase |

