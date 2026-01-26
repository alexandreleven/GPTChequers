"""Elasticsearch request builders for Onyx."""

from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from uuid import UUID

from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import BOOST
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import CONTENT
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    CONTENT_SUMMARY,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    DOC_TIME_DECAY,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    DOC_UPDATED_AT,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import EMBEDDINGS
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import HIDDEN
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import MIN_YEAR
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    SKIP_TITLE_EMBEDDING,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import SOURCE_TYPE
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import TENANT_ID
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import TITLE
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    TITLE_CONTENT_RATIO,
)
from eleven.onyx.document_index.elasticsearch.elasticsearch_constants import (
    TITLE_EMBEDDING,
)
from onyx.context.search.models import IndexFilters
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.model_server_models import Embedding

OR_LOGIC_FIELDS = ["transaction", "follow_up"]
CONFIDENTIAL_COMPANY = []

logger = setup_logger()


def build_elastic_filters(
    filters: IndexFilters,
    *,
    include_hidden: bool = False,
    user_id: Optional[UUID] = None,
    db_session=None,
) -> List[Dict[str, Any]]:
    """Build Elasticsearch filter clauses from IndexFilters.

    This function is similar to build_vespa_filters but returns a list of Elasticsearch
    filter clauses instead of a Vespa YQL string.

    Args:
        filters: The IndexFilters object containing filter criteria.
        include_hidden: Whether to include hidden documents in the results.
        user_id: Optional user ID to apply SharePoint access filtering.
        db_session: Optional database session for SharePoint filtering.
        disable_sharepoint_filter: When set to True, SharePoint access filtering will be skipped.
            Default value is loaded from DISABLE_SHAREPOINT_FILTER in chat_configs.py.

    Returns:
        A list of Elasticsearch filter clauses.
    """
    filter_clauses = []

    # Handle hidden documents
    if not include_hidden:
        filter_clauses.append({"term": {HIDDEN: False}})

    if not filters:
        return filter_clauses

    # If running in multi-tenant mode, we may want to filter by tenant_id
    if filters.tenant_id and MULTI_TENANT:
        filter_clauses.append({"term": {TENANT_ID: filters.tenant_id}})

    # Handle source type
    if filters.source_type:
        source_strs = [s.value for s in filters.source_type]
        if source_strs:
            source_clauses = []
            for source in source_strs:
                source_clauses.append({"term": {SOURCE_TYPE: source}})

            if source_clauses:
                filter_clauses.append(
                    {"bool": {"should": source_clauses, "minimum_should_match": 1}}
                )

    # Filter on tags (field METADATA_LIST, type keyword)
    if filters.tags:
        logger.debug(f"Filters tags: {filters.tags}")
        tag_groups = {}
        for tag in filters.tags:
            tag_key = tag.tag_key
            normalized_tag_key = tag_key.replace(" ", "_").lower()
            if normalized_tag_key == MIN_YEAR:
                normalized_tag_key = "year"
            if normalized_tag_key not in tag_groups:
                tag_groups[normalized_tag_key] = []

            if tag_key == "Fund":
                normalized_tag_value = tag.tag_value
            else:
                normalized_tag_value = tag.tag_value.replace(" ", "").lower()
            tag_groups[normalized_tag_key].append(normalized_tag_value)

        if "year" in tag_groups:
            # Get the minimum year from the selected values
            min_years = [int(year) for year in tag_groups["year"]]
            min_selected_year = min(min_years)
            current_year = datetime.now().year

            # Generate all years from min_selected_year to current_year
            all_years = [
                str(year) for year in range(min_selected_year, current_year + 1)
            ]

            # Replace the original values with the complete range
            tag_groups["year"] = all_years
            logger.debug(
                f"Expanded min_year range from {min_selected_year} to {current_year}: {all_years}"
            )

        if tag_groups:
            # Special handling for transaction and follow_up fields (OR relationship)
            special_fields = OR_LOGIC_FIELDS
            special_clauses = []

            # Collect all the special field values
            for field in special_fields:
                if field in tag_groups:
                    values = tag_groups[field]
                    if len(values) > 1:
                        special_clauses.append(
                            {"terms": {f"metadata.{field}.keyword": values}}
                        )
                    else:
                        special_clauses.append(
                            {"term": {f"metadata.{field}.keyword": values[0]}}
                        )
                    # Remove the special fields from tag_groups to avoid processing them twice
                    tag_groups.pop(field)

            # Add the combined OR clause for special fields if any exist
            if special_clauses:
                filter_clauses.append(
                    {"bool": {"should": special_clauses, "minimum_should_match": 1}}
                )

            # Process the remaining fields with normal AND relationship
            for tag_key, values in tag_groups.items():
                if len(values) > 1:
                    filter_clauses.append(
                        {"terms": {f"metadata.{tag_key}.keyword": values}}
                    )
                else:
                    filter_clauses.append(
                        {"term": {f"metadata.{tag_key}.keyword": values[0]}}
                    )
    return filter_clauses


def build_hybrid_search_query(
    query: str,
    query_embedding: Embedding,
    filter_clauses: List[Dict[str, Any]],
    hybrid_alpha: float,
    time_decay_multiplier: float,
) -> Dict[str, Any]:
    """Build a hybrid search query for Elasticsearch that mimics Vespa's ranking logic.

    This function creates a function_score query that combines vector similarity,
    BM25 text matching, document boost, and recency bias, similar to Vespa's
    hybrid_search ranking profile.

    Args:
        query: The text query.
        query_embedding: The embedding vector for the query.
        filter_clauses: The filter clauses to apply.
        hybrid_alpha: The weight to give to vector similarity vs BM25 (0-1).
        time_decay_multiplier: The multiplier for time decay.

    Returns:
        An Elasticsearch query dict.
    """

    # NOTE This query is still under debugging
    # Create the hybrid search query that combines vector similarity, BM25, document boost, and recency
    script_query = {
        "function_score": {
            "query": {
                "bool": {
                    "should": [
                        # Match all to ensure all documents are considered for vector scoring
                        {"match_all": {}},
                        # Keyword matching for content and title
                        {"match": {CONTENT: query}},
                        {"match": {TITLE: {"query": query, "boost": 2.0}}},
                    ],
                    "filter": filter_clauses,
                    "minimum_should_match": 1,
                }
            },
            "functions": [
                # Vector similarity component
                {
                    "script_score": {
                        "script": {
                            "source": f"""
                                // Vector similarity component with title-content weighting
                                double content_vector_sim = 0.0;
                                double title_vector_sim = 0.0;
                                // Safely get content vector similarity
                                if (doc.containsKey('{EMBEDDINGS}')) {{
                                    content_vector_sim = cosineSimilarity(params.query_vector, '{EMBEDDINGS}');
                                }}
                                // Check if title embedding exists and is not to be skipped
                                if (doc.containsKey('{TITLE_EMBEDDING}') &&
                                    (!doc.containsKey('{SKIP_TITLE_EMBEDDING}') || doc['{SKIP_TITLE_EMBEDDING}'].value == false))
                                {{
                                    title_vector_sim = cosineSimilarity(params.query_vector, '{TITLE_EMBEDDING}');
                                }}
                                // Use max of content and title vector similarity
                                double max_vector_sim = Math.max(content_vector_sim, title_vector_sim);

                                // Apply title-content ratio weighting to vector scores
                                double vector_score = (params.title_content_ratio * max_vector_sim) +
                                                     ((1 - params.title_content_ratio) * content_vector_sim);

                                // Return the weighted vector score, ensuring it's never negative
                                return Math.max(0.0, vector_score * params.alpha);
                            """,
                            "params": {
                                "query_vector": query_embedding,
                                "alpha": hybrid_alpha,
                                "title_content_ratio": TITLE_CONTENT_RATIO,
                            },
                        }
                    },
                    "weight": 1,
                },
                # BM25 text similarity component
                {
                    "script_score": {
                        "script": {
                            "source": """
                            // Get the BM25 score from _score
                            double bm25_score = _score;
                            // Return the weighted BM25 score
                            return bm25_score * (1 - params.alpha);
                            """,
                            "params": {
                                "alpha": hybrid_alpha,
                            },
                        }
                    },
                    "weight": 1,
                },
                # Document boost component (user feedback)
                {
                    "script_score": {
                        "script": {
                            "source": f"""
                            // Document boost based on user feedback (sigmoid function)
                            double boost = 0.0;
                            if (doc.containsKey('{BOOST}')) {{
                                boost = doc['{BOOST}'].value;
                            }}
                            double boost_factor;
                            if (boost < 0) {{
                                boost_factor = 0.5 + (1.0 / (1.0 + Math.exp(-boost / 3.0)));
                            }} else {{
                                boost_factor = 2.0 / (1.0 + Math.exp(-boost / 3.0));
                            }}
                            return boost_factor;
                            """
                        }
                    },
                    "weight": 1,
                },
                # Recency bias component
                {
                    "script_score": {
                        "script": {
                            "source": f"""
                            // Time decay calculation
                            long now = System.currentTimeMillis() / 1000; // current time in seconds
                            long doc_time;
                            // Safely check if doc_updated_at exists and get its value
                            if (doc.containsKey('{DOC_UPDATED_AT}')) {{
                                // For date fields, we need to get the value in millis and convert to seconds
                                doc_time = doc['{DOC_UPDATED_AT}'].value.toInstant().toEpochMilli() / 1000;
                            }} else {{
                                // Default to 3 months ago if no date is present
                                doc_time = now - 7890000;
                            }}
                            // Convert to years (same as Vespa)
                            double doc_age_years = Math.max((now - doc_time) / 31536000.0, 0);
                            // Apply decay factor (same formula as Vespa)
                            double recency_factor = Math.max(1.0 / (1.0 + params.decay_factor * doc_age_years), 0.75);
                            return recency_factor;
                            """,
                            "params": {
                                "decay_factor": DOC_TIME_DECAY * time_decay_multiplier
                            },
                        }
                    },
                    "weight": 1,
                },
            ],
            "score_mode": "multiply",  # Multiply all function scores together
            "boost_mode": "replace",  # Replace the original score
        }
    }

    return script_query


def build_admin_search_query(
    query: str,
    filter_clauses: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build an admin search query for Elasticsearch that mimics Vespa's admin_search ranking profile.

    This function creates a query that prioritizes title matches over content matches,
    similar to Vespa's admin_search ranking profile. It also includes exact matching capabilities
    for better handling of file name searches.

    Args:
        query: The text query.
        filter_clauses: The filter clauses to apply.

    Returns:
        An Elasticsearch query dict.
    """
    # Create a query that prioritizes title matches (5x boost) over content matches
    # This mimics Vespa's admin_search ranking profile: bm25(content) + (5 * bm25(title))
    query_body = {
        "bool": {
            "should": [
                # Exact match on title with highest boost (10x)
                {"term": {f"{TITLE}.keyword": {"value": query, "boost": 10.0}}},
                # Phrase match on title with high boost (7x)
                {"match_phrase": {TITLE: {"query": query, "boost": 7.0}}},
                # Title match with 5x boost to match Vespa's admin_search profile
                {"match": {TITLE: {"query": query, "boost": 5.0}}},
                # Exact match on content with boost (3x)
                {"match_phrase": {CONTENT: {"query": query, "boost": 3.0}}},
                # Content match with normal weight
                {"match": {CONTENT: query}},
                # Add match on content_summary for highlighting, similar to Vespa
                {"match": {CONTENT_SUMMARY: query}},
                # Fuzzy match on title for typo tolerance
                {"fuzzy": {TITLE: {"value": query, "boost": 2.0, "fuzziness": "AUTO"}}},
            ],
            "filter": filter_clauses,
            "minimum_should_match": 1,
        }
    }

    return query_body


def build_random_search_query(
    filter_clauses: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a random search query for Elasticsearch.

    This function creates a query that returns random documents,
    similar to Vespa's random_ ranking profile.

    Args:
        filter_clauses: The filter clauses to apply.

    Returns:
        An Elasticsearch query dict.
    """
    # Create a query that returns random documents
    query_body = {
        "function_score": {
            "query": {"bool": {"must": {"match_all": {}}, "filter": filter_clauses}},
            "random_score": {},
            "boost_mode": "replace",  # Replace the original score with the random score
        }
    }

    return query_body


def extract_access_lists(
    site_library_access: Optional[List[List[str]]],
) -> tuple[List[str], List[str]]:
    """Extract site_users and drive_users from site_library_access data.

    Args:
        site_library_access: A list of [site, library] pairs representing access rights.

    Returns:
        A tuple of (site_users, drive_users) lists.
    """
    site_users = []
    drive_users = []

    if site_library_access:
        for access_pair in site_library_access:
            if len(access_pair) == 2:
                site, library = access_pair
                site_users.append(site)
                drive_users.append(library)

    # Remove duplicates while preserving order
    site_users = list(dict.fromkeys(site_users))
    drive_users = list(dict.fromkeys(drive_users))

    return site_users, drive_users
