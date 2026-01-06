from elasticsearch import Elasticsearch


def get_elasticsearch_client() -> Elasticsearch:

    return Elasticsearch()
