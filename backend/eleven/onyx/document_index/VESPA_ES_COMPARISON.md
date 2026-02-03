# Elasticsearch vs Vespa: Technical Comparison

This document compares Elasticsearch and Vespa implementations in the Onyx codebase, focusing on indexing, retrieval, filtering, and ranking capabilities. 


## Code Reference

### Elasticsearch Implementation

**Main Classes & Files:**
- `ElasticsearchIndex` (`backend/eleven/onyx/document_index/elasticsearch/index.py`): Main index class implementing `OldDocumentIndex`
  - `hybrid_retrieval()`: Hybrid search using RRF
  - `id_based_retrieval()`: Retrieve chunks by document ID
  - `update()`: Update document fields
  - `ensure_indices_exist()`: Create indices using `MAPPING_TEMPLATE` from `elasticsearch_constants.py`
- `ElasticsearchSchema` (`backend/eleven/onyx/document_index/elasticsearch/schema.py`): Schema definition class (not currently used in production; mapping is defined in `elasticsearch_constants.py`)
  - `get_document_schema()`: Generate mappings (not used)
  - `get_index_settings()`: Index settings (not used)
- `prepare_elasticsearch_document()` (`backend/eleven/onyx/document_index/elasticsearch/indexing_utils.py`): Format chunks for indexing (transforms `DocMetadataAwareIndexChunk` to Elasticsearch document structure - this is where document formatting happens, not in `schema.py`)
- `build_elastic_filters()` (`backend/eleven/onyx/document_index/elasticsearch/shared_utils/elasticsearch_request_builders.py`): Build filter clauses
- `query_elasticsearch()` (`backend/eleven/onyx/document_index/elasticsearch/chunk_retrieval.py`): Execute search queries

**Constants & Mapping:**
- `backend/eleven/onyx/document_index/elasticsearch/elasticsearch_constants.py`: Field names, index settings, and `MAPPING_TEMPLATE` (the actual mapping used in production)

### Vespa Implementation

**Main Classes & Files:**
- `VespaDocumentIndex` (`backend/onyx/document_index/vespa/vespa_document_index.py`): Main index class implementing `DocumentIndex`
  - `hybrid_retrieval()`: Hybrid search with multi-phase ranking
  - `id_based_retrieval()`: Retrieve chunks by document ID
- `VespaIndex` (`backend/onyx/document_index/vespa/index.py`): Legacy Vespa index class
  - `hybrid_retrieval()`: Legacy hybrid search implementation
- `_index_vespa_chunk()` (`backend/onyx/document_index/vespa/indexing_utils.py`): Index a single chunk
- `build_vespa_filters()` (`backend/onyx/document_index/vespa/shared_utils/vespa_request_builders.py`): Build YQL filter string
- `query_vespa()` (`backend/onyx/document_index/vespa/chunk_retrieval.py`): Execute YQL queries

**Schema & Configuration:**
- `backend/onyx/document_index/vespa/app_config/schemas/danswer_chunk.sd.jinja`: Vespa schema definition with ranking profiles
- `backend/onyx/document_index/vespa_constants.py`: Field names and constants

**Shared Models:**
- `IndexFilters` (`backend/onyx/context/search/models.py`): Filter criteria used by both systems
- `DocMetadataAwareIndexChunk` (`backend/onyx/indexing/models.py`): Chunk model for indexing

---

## Part 1: Indexing & Retrieval Basics

### 1.1 Elasticsearch

#### Index Creation

Elasticsearch requires explicit mappings (schema) and settings when creating an index. While `ElasticsearchSchema` exists in `backend/eleven/onyx/document_index/elasticsearch/schema.py`, it is not currently used in production. Instead, mappings are defined in `MAPPING_TEMPLATE` (`backend/eleven/onyx/document_index/elasticsearch/elasticsearch_constants.py`) and used when creating indices via `ElasticsearchIndex.ensure_indices_exist()`.

**Important Settings:**
- `number_of_shards`: How many shards to split data across (affects parallel query performance)
- `number_of_replicas`: How many copies of each shard (for redundancy and read scaling)
- `analysis`: Text processing configuration (tokenization, stemming)

```json
{
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1,
    "analysis": {"analyzer": {"default": {"type": "standard"}}}
  }
}
```

#### Mapping / Schema Definition

Mappings define field types and how they're indexed. Set at index creation, can be extended later (with limitations).

**Important Field Types:**
- `text`: Full-text searchable (analyzed)
- `keyword`: Exact match only (not analyzed)
- `dense_vector`: Vector embeddings for similarity search
- `nested`: Complex objects with relationships

**Current Mapping:**

While `ElasticsearchSchema` in `backend/eleven/onyx/document_index/elasticsearch/schema.py` provides a `get_document_schema()` method, it is not currently used. The actual mapping is defined in `MAPPING_TEMPLATE` (`backend/eleven/onyx/document_index/elasticsearch/elasticsearch_constants.py`). Field dimensions (`VARIABLE_DIM`) are replaced with actual embedding dimensions when creating indices.

```json
{
  "mappings": {
    "properties": {
      "tenant_id": {"type": "keyword"},
      "document_id": {"type": "keyword"},
      "chunk_id": {"type": "integer"},
      "blurb": {"type": "text"},
      "content": {"type": "text"},
      "source_type": {"type": "keyword"},
      "source_links": {"type": "object"},
      "semantic_identifier": {"type": "text"},
      "title": {"type": "text"},
      "section_continuation": {"type": "boolean"},
      "embeddings": {
        "type": "dense_vector",
        "dims": "VARIABLE_DIM",
        "index": true,
        "similarity": "cosine"
      },
      "title_embedding": {
        "type": "dense_vector",
        "dims": "VARIABLE_DIM",
        "index": true,
        "similarity": "cosine"
      },
      "skip_title": {"type": "boolean"},
      "access_control_list": {
        "type": "nested",
        "properties": {
          "value": {"type": "keyword"},
          "weight": {"type": "integer"}
        }
      },
      "document_sets": {
        "type": "nested",
        "properties": {
          "value": {"type": "keyword"},
          "weight": {"type": "integer"}
        }
      },
      "large_chunk_reference_ids": {"type": "integer"},
      "metadata": {"type": "object"},
      "metadata_list": {"type": "keyword"},
      "metadata_suffix": {"type": "keyword"},
      "boost": {"type": "float"},
      "doc_updated_at": {"type": "date", "format": "epoch_second"},
      "primary_owners": {"type": "keyword"},
      "secondary_owners": {"type": "keyword"},
      "recency_bias": {"type": "float"},
      "hidden": {"type": "boolean"},
      "user_project": {"type": "integer"},
      "content_summary": {"type": "text"},
      "image_file_name": {"type": "keyword"},
      "doc_summary": {"type": "text"},
      "chunk_context": {"type": "text"}
    }
  }
}
```

#### Document Ingestion

Documents are indexed via Bulk API or single document API. Structure must match the mapping.

**Process:** Documents come from `DocMetadataAwareIndexChunk` objects (`backend/onyx/indexing/models.py`), are formatted via `prepare_elasticsearch_document()` (`backend/eleven/onyx/document_index/elasticsearch/indexing_utils.py`) which transforms chunks into Elasticsearch document structure. Note: Document formatting happens in `prepare_elasticsearch_document()`, not in `schema.py` (which is not used). Documents are then indexed in batches using the Bulk API via `ElasticsearchIndex.index()` (`backend/eleven/onyx/document_index/elasticsearch/index.py`). 

#### Retrieval (Search)

Elasticsearch supports multiple retrieval strategies:

**1. Standard Text Search (BM25):**
```json
{
  "query": {
            "multi_match": {
      "query": "search terms",
                "fields": [
        "semantic_identifier^3.0",
        "content^7.0"
                ],
                "type": "best_fields",
      "tie_breaker": 0.3
    }
  }
}
```

**How BM25 Works:** BM25 only searches text fields (not vectors). It matches query terms against indexed text content.

- `semantic_identifier`: Document title/identifier field (gets 3x boost)
- `content`: Main document content field (gets 7x boost)
- `type: "best_fields"`: Uses the highest score from matching fields (title OR content)
- `tie_breaker: 0.3`: Adds 30% of other field scores to prevent ties—if title matches well, content match still contributes

**Why This Matters:** `best_fields` prioritizes strong matches in one field (e.g., title), while `tie_breaker` ensures content relevance still influences ranking. This balances exact title matches with content relevance.

**2. Vector Similarity Search (KNN):**
```json
{
  "knn": {
    "field": "embeddings",
    "query_vector": [0.1, 0.2, ...],
    "k": 10,
    "num_candidates": 10000,
    "filter": {
      "bool": {
        "must": [...]
      }
    }
  }
}
```

**Why `num_candidates: 10000`?** KNN search uses approximate nearest neighbor (HNSW index). `num_candidates` is the initial candidate pool size before filtering and final ranking. Larger values improve recall (find more relevant docs) but slow down queries. 10000 is a good balance—searches through 10k candidates to find the top 10 results (`k=10`), ensuring high recall while maintaining performance. 

**3. Hybrid Search (Reciprocal Rank Fusion):**

This is the main search function used in production. Note: `admin_search` and `random_retrieval` functions exist but are not used in the current codebase.
```json
{
            "retriever": {
                "rrf": {
      "retrievers": [
        {
          "standard": {
            "query": {...}
          }
        },
        {
                "knn": {
            "field": "embeddings",
            "query_vector": [...],
            "k": 10
          }
        }
      ],
      "rank_window_size": 20,
      "rank_constant": 60
    }
  }
}
```

**RRF Parameters:**
- `rank_window_size: 20`: How many top results from each retriever (BM25 and KNN) are considered for fusion. Only the top 20 from each retriever participate in RRF.
- `rank_constant: 60`: Smoothing parameter for RRF formula. Higher values (60) make ranking more uniform—less difference between ranks. Lower values (20 for keyword queries) preserve more of the original ranking differences. 60 works well for semantic queries where you want balanced fusion.

**Why These Values:** `rank_window_size=20` limits fusion to top candidates (faster). `rank_constant=60` (semantic) vs `20` (keyword) reflects that semantic queries benefit from more uniform fusion, while keyword queries preserve ranking signals better with lower constant.

**Why RRF?** Elasticsearch doesn't support alpha-weighted hybrid search—you cannot directly control the weight between BM25 and vector similarity scores. RRF merges results from separate BM25 and KNN retrievers without needing to normalize or weight scores manually. It's simpler but less flexible than Vespa's weighted combination approach. 

**Implementation:** See `ElasticsearchIndex.hybrid_retrieval()` in `backend/eleven/onyx/document_index/elasticsearch/index.py` (lines 520-630).

#### Filtering & Querying

Elasticsearch separates queries (affect scoring) from filters (yes/no inclusion, cached for performance).

**Filter Example:**
```json
{
  "bool": {
    "must": [
      {"term": {"hidden": false}},
      {"term": {"tenant_id": "tenant-1"}}
    ],
    "should": [
      {"term": {"source_type": "web"}},
      {"term": {"source_type": "slack"}}
    ],
    "minimum_should_match": 1,
    "filter": [
      {"range": {"doc_updated_at": {"gte": 1704067200}}}
    ]
  }
}
```

**Implementation:** Filters built by `build_elastic_filters()` (`backend/eleven/onyx/document_index/elasticsearch/shared_utils/elasticsearch_request_builders.py`).

**Key Points:**
- Filters are cached automatically (queries are not)
- `minimum_should_match`: Controls OR logic (how many `should` clauses must match)
- Nested fields need explicit `nested` wrapper
- Field boosts: `field^2.0` increases that field's importance

**Scoring in Hybrid Search:**

Elasticsearch uses field boosts in the BM25 query to weight title vs content:
- `semantic_identifier^3.0`: Title field gets 3x boost (when `title_content_ratio=0.3`, boost = 0.3 * 10 = 3.0)
- `content^7.0`: Content field gets 7x boost (when `title_content_ratio=0.3`, boost = 0.7 * 10 = 7.0)

These boosts are applied during BM25 scoring. The BM25 retriever and KNN retriever run separately, then RRF merges their results. Unlike Vespa, Elasticsearch cannot directly combine BM25 and vector scores with a configurable alpha weight—RRF handles the fusion automatically.

**Implementation:** Title/content boosts calculated in `ElasticsearchIndex.hybrid_retrieval()` (`backend/eleven/onyx/document_index/elasticsearch/index.py`, lines 560-561). Filter building in `build_elastic_filters()` (`backend/eleven/onyx/document_index/elasticsearch/shared_utils/elasticsearch_request_builders.py`). 

---

### 1.2 Vespa

#### Schema Definition

Vespa uses schema files (`.sd`) that define document structure, indexing behavior, and ranking profiles. Schemas are versioned and deployed together as an application package.

**Schema Structure:**
```vespa
schema {{ schema_name }} {
    document {{ schema_name }} {
        field document_id type string {
            indexing: summary | attribute
            rank: filter
            attribute: fast-search
        }
        field content type string {
            indexing: summary | index
            index: enable-bm25
        }
        field title type string {
            indexing: summary | index | attribute
            index: enable-bm25
        }
        field embeddings type tensor<float>(t{},x[768]) {
            indexing: attribute | index
            attribute {
                distance-metric: angular
            }
        }
        field access_control_list type weightedset<string> {
            indexing: summary | attribute
            rank: filter
            attribute: fast-search
        }
        # ... other fields similar to Elasticsearch
    }
}
```

**Schema Comparison:** Vespa and Elasticsearch use similar field structures but different syntax. Vespa uses `.sd` files with declarative syntax; Elasticsearch uses JSON mappings. Key difference: Vespa supports `weightedset` for access control (simpler than Elasticsearch's `nested`), and Vespa's schema includes ranking profiles.

**Files:** Vespa schema in `backend/onyx/document_index/vespa/app_config/schemas/danswer_chunk.sd.jinja`. Elasticsearch: `ElasticsearchSchema` exists in `backend/eleven/onyx/document_index/elasticsearch/schema.py` but is not currently used; the actual mapping is in `backend/eleven/onyx/document_index/elasticsearch/elasticsearch_constants.py` (`MAPPING_TEMPLATE`).

**Important Schema Parameters:**
- `indexing`: What happens during indexing
  - `index`: Makes field searchable
  - `attribute`: Stores in memory for fast filtering
  - `summary`: Included in results
- `rank: filter`: Field can filter but doesn't affect ranking
- `distance-metric`: Vector similarity (`angular` = cosine similarity)

#### Document Feeding

Documents are fed to Vespa via the Document API (HTTP REST). Each document must match the schema definition.

**Important Notes:**
- No native batch API (use parallel threads)
- Documents are immediately searchable (no refresh needed)
- Updates are atomic per document

**Implementation:** Document feeding via `_index_vespa_chunk()` (`backend/onyx/document_index/vespa/indexing_utils.py`, line 135).

#### Indexing Pipeline

Vespa processes documents through a pipeline: validates structure, builds indexes (BM25 for text, HNSW for vectors), and stores attributes in memory for fast filtering.

#### Retrieval

Vespa uses YQL (Yahoo Query Language) for query specification and ranking profiles for scoring.


**Important Parameters:**
- `yql`: The YQL query string
- `query`: Text query for `userInput()` function
- `hits`: Number of results
- `ranking.profile`: Which ranking profile to use
- `input.query(name)`: Query-time parameters for ranking (e.g., `alpha`, `title_content_ratio`)
- `targetHits`: Vector search candidates (must be >= `rerank-count` in ranking profile)

#### Filtering & Ranking

Vespa separates filtering (YQL `where` clause) from ranking (ranking profile). Filters are applied before ranking and use attribute-based fast filtering.

**Filter Syntax:**
```yql
where (
    !(hidden=true)
    and (tenant_id contains "tenant-1")
    and (source_type contains "web" or source_type contains "slack")
    and (doc_updated_at >= 1704067200)
    and (access_control_list contains "user-1")
)
```

**Implementation:** Filters built by `build_vespa_filters()` (`backend/onyx/document_index/vespa/shared_utils/vespa_request_builders.py`, line 32).

**Filter Operators:**
- `contains`: Check if array/weightedset contains value (most common for filtering)
- `=`, `>=`, `<=`: Standard comparison operators
- `and`, `or`, `!`: Logical operators

**Ranking Profiles:**

Ranking profiles define scoring logic. Vespa's key advantage is multi-phase ranking:

**Simple Explanation of Vespa Ranking:**

1. **First Phase (Fast)**: Scores all matching documents using cheap operations (e.g., vector similarity). This quickly filters to top candidates.

2. **Global Phase (Expensive)**: Takes the top N documents from first phase (e.g., top 1000) and re-ranks them with expensive operations:
   - Normalizes scores (so BM25 and vector scores can be compared)
   - Combines them with weights: `alpha * vector_score + (1-alpha) * bm25_score`
   - Applies boosts: document feedback, recency bias, chunk quality

**Why This Works:** Instead of running expensive normalization and combination on millions of documents, you only do it on the top 1000. This is much faster while maintaining quality.

**Example Ranking Profile:**
```vespa
rank-profile hybrid_search_semantic_base_768 inherits default_rank {
    inputs {
        query(query_embedding) tensor<float>(x[768])
        query(alpha) double
        query(title_content_ratio) double
        query(decay_factor) double
    }
    
    first-phase {
        expression: query(title_content_ratio) * closeness(field, title_embedding) 
                   + (1 - query(title_content_ratio)) * closeness(field, embeddings)
    }
    
    global-phase {
        expression {
            (
                query(alpha) * (
                    (query(title_content_ratio) * normalize_linear(title_vector_score))
                    + ((1 - query(title_content_ratio)) * normalize_linear(closeness(field, embeddings)))
                )
                +
                (1 - query(alpha)) * (
                    (query(title_content_ratio) * normalize_linear(bm25(title)))
                    + ((1 - query(title_content_ratio)) * normalize_linear(bm25(content)))
                )
            )
            * document_boost
            * recency_bias
            * aggregated_chunk_boost
        }
        rerank-count: 1000
    }
}
```

**Parameter Values (from code):**
- `alpha`: 
  - `0.2` for KEYWORD queries (`KEYWORD_QUERY_HYBRID_ALPHA`)
  - `0.5` for SEMANTIC queries (`HYBRID_ALPHA`)
- `title_content_ratio`: `0.3` (30% title, 70% content)
- `decay_factor`: `DOC_TIME_DECAY * RECENCY_BIAS_MULTIPLIER` = `0.5 * 1.0` = `0.5` (default)
- `rerank-count`: `1000` (number of documents re-ranked in global phase)
- `targetHits`: `max(10 * num_to_retrieve, 1000)` (must be >= rerank-count)

**Implementation:** Parameters passed via `input.query()` in `VespaDocumentIndex.hybrid_retrieval()` (`backend/onyx/document_index/vespa/vespa_document_index.py`, lines 660-671).

**How Multi-Phase Ranking Works:**
1. **First Phase**: Fast ranking on all matching documents (cheap operations)
2. **Global Phase**: Expensive ranking on top N only (complex expressions, normalization)
3. This optimization is Vespa's key advantage: expensive operations run on fewer documents

**Implementation:** Ranking profiles defined in `backend/onyx/document_index/vespa/app_config/schemas/danswer_chunk.sd.jinja`. Hybrid retrieval in `VespaDocumentIndex.hybrid_retrieval()` (`backend/onyx/document_index/vespa/vespa_document_index.py`, line 614).

**Important Ranking Functions:**
- `bm25(field)`: Text relevance score
- `closeness(field, query_vector)`: Vector similarity
- `query(name)`: Access query-time parameters (e.g., `query(alpha)` for hybrid weighting)
- `normalize_linear()`: Normalize scores for better combination

---

## Part 2: Elasticsearch vs Vespa: Deep Comparison

### 2.1 Retrieval & Filtering Differences

**Key Difference: Indexing vs Retrieval**

Indexing is similar between both systems—both take document chunks, prepare fields, and store them. The **critical differences are in retrieval parameters and how queries are executed**.

**Limitation:** Elasticsearch doesn't support alpha-weighted hybrid search—you cannot directly control the weight between BM25 and vector similarity scores. RRF merges results automatically. You're stuck with RRF's fusion algorithm—you can't say "give me 70% vector, 30% BM25" like you can with Vespa's `alpha` parameter.

**Elasticsearch Retrieval Parameters:**
- `rank_window_size`: 20 (RRF candidate window)
- `rank_constant`: 20 (keyword) or 60 (semantic) - RRF smoothing
- `num_candidates`: 
  - `10000` for semantic queries (KNN search)
  - `num_to_retrieve * 5` for keyword queries (smaller pool, faster) 
- `title_boost`: `title_content_ratio * 10` = 3.0 (when ratio=0.3)
- `content_boost`: `(1 - title_content_ratio) * 10` = 7.0
- **Cannot control alpha** (BM25 vs vector weight) - RRF handles fusion automatically

**Vespa Retrieval Parameters:**
- `alpha`: 0.2 (keyword) or 0.5 (semantic) - **direct control** over vector vs BM25 weight
- `title_content_ratio`: 0.3 - **query-time parameter** passed to ranking expression
- `decay_factor`: 0.5 - **query-time parameter** for recency bias
- `targetHits`: `max(10 * num_to_retrieve, 1000)` - vector search candidates
- `rerank-count`: 1000 - documents re-ranked in global phase
- **Full control** over how signals combine in ranking expressions

**The Real Difference:** Elasticsearch uses fixed RRF algorithm with limited tuning (rank_constant, window_size). Vespa gives you query-time control over the entire ranking formula via `input.query()` parameters that feed into ranking expressions. This means you can adjust hybrid weighting (`alpha`), title/content balance (`title_content_ratio`), and recency (`decay_factor`) **per query** without changing code or schema.

| Aspect | Elasticsearch | Vespa |
|--------|--------------|-------|
| **Query Language** | JSON Query DSL | YQL (Yahoo Query Language) |
| **Filter vs Query** | Separate `filter` and `query` clauses; filters cached, queries affect scoring | Filters in YQL `where` clause; ranking separate in ranking profiles |
| **Vector Search** | `knn` query with `num_candidates` parameter | `nearestNeighbor()` function with `targetHits` parameter |
| **Hybrid Search** | Reciprocal Rank Fusion (RRF) via `retriever.rrf` | Multi-phase ranking with weighted combination in ranking profile |
| **Text Search** | `multi_match`, `match`, `match_phrase` queries | `userInput()` function with grammar options |
| **Filter Caching** | Automatic filter cache | Attribute-based filtering (no explicit cache) |
| **Nested Fields** | Explicit `nested` query wrapper required | Array/weightedset fields use `contains` operator |
| **Query-Time Parameters** | Limited (boosts, function_score params) | Extensive via `input.query()` in ranking profiles |

#### Query Model Comparison

**Elasticsearch:** Queries and filters live together in JSON. Filters are cached but don't affect scoring. Hybrid search uses RRF to merge results from multiple retrievers.

**Vespa:** Clean separation: YQL handles filtering (fast, attribute-based), ranking profiles handle scoring (schema-defined, query-time configurable). Hybrid search uses weighted combination in ranking expressions.

#### Filtering Behavior

**Elasticsearch:**
```json
{
  "bool": {
    "must": [
      {"term": {"hidden": false}}
    ],
    "should": [
      {"term": {"source_type": "web"}},
      {"term": {"source_type": "slack"}
    ],
    "minimum_should_match": 1,
    "filter": [
      {"range": {"doc_updated_at": {"gte": 1704067200}}}
    ]
  }
}
```

**Vespa:**
```yql
where (
    !(hidden=true)
    and (source_type contains "web" or source_type contains "slack")
    and (doc_updated_at >= 1704067200)
)
```

**Key Differences:**
- **Syntax**: Elasticsearch uses nested JSON; Vespa uses SQL-like YQL (more readable)
- **OR logic**: Elasticsearch needs `should` + `minimum_should_match`; Vespa uses simple `or`
- **Complex fields**: Elasticsearch requires `nested` wrapper; Vespa uses `contains` for arrays/sets
- **Performance**: Elasticsearch filters cached (variable performance); Vespa attributes in memory (consistently fast but uses more RAM)

#### Hybrid Search: RRF vs Vespa Weighted Combination

| Aspect | Elasticsearch (RRF) | Vespa (Weighted Combination) |
|--------|-------------------|------------------------------|
| **Method** | Reciprocal Rank Fusion merges separate BM25 and KNN retrievers | Weighted combination in ranking expression: `alpha * vector_score + (1-alpha) * bm25_score` |
| **Parameters** | `rank_window_size`: candidates for fusion<br>`rank_constant`: smoothing (20 for keyword, 60 for semantic) | `alpha`: vector vs BM25 weight (0.2 for keyword, 0.5 for semantic)<br>`title_content_ratio`: title vs content weight (0.3) |
| **Scoring** | BM25: field boosts (`semantic_identifier^3.0`, `content^7.0`)<br>KNN: cosine similarity<br>RRF: merges ranks without score normalization | First-phase: fast vector similarity<br>Global-phase: `alpha * (title_ratio * normalize(title_vector) + content_ratio * normalize(content_vector)) + (1-alpha) * (title_ratio * normalize(bm25(title)) + content_ratio * normalize(bm25(content)))`<br>Then multiplies by: `document_boost * recency_bias * aggregated_chunk_boost` |
| **Flexibility** | Limited: RRF is fixed algorithm, can't weight BM25 vs vector per query | High: `alpha` and `title_content_ratio` are query-time parameters, full control over combination |
| **Performance** | Both retrievers run independently, then merge (can be slower) | Multi-phase optimization: expensive operations only on top N documents |

**Key Difference:** Elasticsearch cannot directly weight BM25 vs vector similarity—RRF handles fusion automatically. Vespa gives full control via `alpha` parameter in ranking expressions, allowing fine-tuned hybrid search per query.

**Implementation:** 
- Elasticsearch: `ElasticsearchIndex.hybrid_retrieval()` (`backend/eleven/onyx/document_index/elasticsearch/index.py`, line 520)
- Vespa: `VespaDocumentIndex.hybrid_retrieval()` (`backend/onyx/document_index/vespa/vespa_document_index.py`, line 614)

---

### 2.2 Architectural Differences

| Aspect | Elasticsearch | Vespa |
|--------|--------------|-------|
| **Query Execution** | Distributed: queries split across shards, results merged at coordinator node | Single-node: each query executes on one content node with multi-phase ranking |
| **Scaling Model** | Horizontal: sharding enables parallel query execution across nodes | Vertical: content nodes can replicate, but each query runs on single node |
| **Filtering** | Filter cache: performance depends on cache hit rate (variable) | In-memory attributes: consistently fast filtering, but memory-bound |
| **Configuration** | Runtime: scripts stored in cluster state, mappings can be extended | Schema-driven: versioned application packages, requires redeployment for changes |
| **Design Focus** | General-purpose search engine with broad ecosystem | Specialized for complex ranking and real-time serving |

#### Multi-Tenant Support

**Elasticsearch:** Multi-tenancy handled via `tenant_id` field in mappings. Filtered at query time using `term` filter. Schema supports optional `tenant_id` field (removed if `multitenant=False`).

**Vespa:** Multi-tenancy also uses `tenant_id` field with conditional schema definition (`{% if multi_tenant %}`). Filtered via YQL: `(tenant_id contains "tenant-1")`. Both systems handle multi-tenancy similarly at the field level.

#### Knowledge Graph Support

**Elasticsearch:** Knowledge graph fields (`kg_entities`, `kg_relationships`, `kg_terms`) are not currently in the Elasticsearch schema. Would need to be added as `keyword` arrays or `nested` objects.

**Vespa:** Knowledge graph support built into schema:
- `kg_entities`: `array<string>` with `fast-search` attribute
- `kg_relationships`: `array<kg_relationship>` struct with `source`, `rel_type`, `target` fields
- `kg_terms`: `array<string>` with `fast-search` attribute

Vespa's knowledge graph support is more mature with structured relationship types and efficient filtering via `contains` operator.

---

