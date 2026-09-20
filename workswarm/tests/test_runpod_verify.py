import pytest

from workswarm.runpod_verify import endpoint_urls


@pytest.mark.parametrize(
    ("configured", "root"),
    [
        ("https://pod-8000.proxy.runpod.net", "https://pod-8000.proxy.runpod.net"),
        ("https://pod-8000.proxy.runpod.net/", "https://pod-8000.proxy.runpod.net"),
        ("https://pod-8000.proxy.runpod.net/v1", "https://pod-8000.proxy.runpod.net"),
        ("https://example.invalid/pod/v1/", "https://example.invalid/pod"),
    ],
)
def test_endpoint_urls_accept_service_root_or_openai_base(configured, root):
    urls = endpoint_urls(configured)

    assert urls.service_root == root
    assert urls.openai_base == f"{root}/v1"
    assert urls.health == f"{root}/health"
    assert urls.models == f"{root}/v1/models"
    assert urls.chat_completions == f"{root}/v1/chat/completions"


@pytest.mark.parametrize(
    "unsafe",
    [
        "pod-8000.proxy.runpod.net",
        "ftp://pod.invalid/v1",
        "https://token@pod.invalid/v1",
        "https://pod.invalid/v1?api_key=secret",
        "https://pod.invalid/v1#secret",
    ],
)
def test_endpoint_urls_refuse_ambiguous_or_credential_bearing_urls(unsafe):
    with pytest.raises(ValueError):
        endpoint_urls(unsafe)
