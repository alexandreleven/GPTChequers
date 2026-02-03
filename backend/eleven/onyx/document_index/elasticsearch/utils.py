import time

from elasticsearch import Elasticsearch

from eleven.onyx.configs.app_configs import ELASTICSEARCH_API_KEY
from eleven.onyx.configs.app_configs import ELASTICSEARCH_CLOUD_URL
from eleven.onyx.configs.app_configs import ELASTICSEARCH_REQUEST_TIMEOUT
from eleven.onyx.configs.app_configs import MANAGED_ELASTICSEARCH
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_elasticsearch_client(no_timeout: bool = False) -> Elasticsearch:
    """
    Configure and return an Elasticsearch client,
    including authentication if needed.
    """
    return Elasticsearch(
        ELASTICSEARCH_CLOUD_URL,
        api_key=ELASTICSEARCH_API_KEY,
        verify_certs=False if not MANAGED_ELASTICSEARCH else True,
        timeout=None if no_timeout else ELASTICSEARCH_REQUEST_TIMEOUT,
    )


# TODO check if we transform this in a more meta function
def wait_for_elasticsearch_with_timeout(
    wait_interval: int = 5, wait_limit: int = 60, index_name: str = None
) -> bool:
    """Waits for Elasticsearch to become ready subject to a timeout.
    If index_name is provided, also checks that the index exists and is healthy.
    Returns True if Elasticsearch is ready, False otherwise."""

    time_start = time.monotonic()
    logger.info("Elasticsearch: Readiness probe starting.")

    while True:
        try:
            client = get_elasticsearch_client(no_timeout=True)
            health = client.cluster.health()
            status = health["status"]

            if status in ["green", "yellow"]:
                logger.info(
                    f"Elasticsearch: Readiness probe successful. Cluster status: {status}"
                )

                # If an index name is provided, check that the index exists and is healthy
                if index_name:
                    # Check if index exists
                    if not client.indices.exists(index=index_name):
                        logger.warning(
                            f"Elasticsearch: Index {index_name} does not exist yet."
                        )
                        time.sleep(wait_interval)
                        continue

                    # Check index health
                    index_health = client.cluster.health(
                        index=index_name,
                        wait_for_status="yellow",
                        timeout=f"{wait_interval}s",
                    )
                    index_status = index_health.get("status")

                    if index_status not in ["green", "yellow"]:
                        logger.warning(
                            f"Elasticsearch: Index {index_name} has status {index_status}, waiting..."
                        )
                        time.sleep(wait_interval)
                        continue

                    logger.info(f"Elasticsearch: Index {index_name} is ready.")

                return True
            else:
                logger.warning(
                    f"Elasticsearch: Cluster status is {status}, waiting for improvement..."
                )
        except Exception as e:
            logger.debug(f"Elasticsearch: Health check failed with error: {str(e)}")

        time_elapsed = time.monotonic() - time_start
        if time_elapsed > wait_limit:
            logger.info(
                "Elasticsearch: Readiness probe did not succeed within the timeout "
                f"({wait_limit} seconds)."
            )
            return False

        time.sleep(wait_interval)
