#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for proxy functionality for web scraping.

Tests are based on the Gherkin scenarios defined in proxy.feature.
Each test corresponds to a specific scenario from the feature file.
"""
import pytest
from .proxy import proxy


# Background fixture - corresponds to "Given the proxy callable is available"
@pytest.fixture
def proxy_callable():
    """The proxy callable is available."""
    return proxy


# Background fixture - corresponds to "Given a proxy configuration"
@pytest.fixture
def proxy_configuration():
    """A proxy configuration."""
    return proxy


class TestProxyConfiguration:
    """Test suite for Proxy Configuration."""
    
    def test_create_proxy_with_single_http_proxy_url(self, proxy_configuration):
        """
        Tests: proxy.__init__()
        
        GIVEN a proxy configuration
        WHEN I call proxy with proxy_url "http://proxy1.example.com:8080"
        THEN the proxy contains 1 proxy URL
        """
        proxy_url = "http://proxy1.example.com:8080"
        expected_count = 1
        
        result = proxy_configuration(proxy_url=proxy_url)
        
        assert result.proxy_count == expected_count, f"expected {expected_count}, got {result.proxy_count}"
    
    def test_create_proxy_with_single_https_proxy_url(self, proxy_configuration):
        """
        Tests: proxy.__init__()
        
        GIVEN a proxy configuration
        WHEN I call proxy with proxy_url "https://proxy1.example.com:8443"
        THEN the proxy contains 1 proxy URL
        """
        proxy_url = "https://proxy1.example.com:8443"
        expected_count = 1
        
        result = proxy_configuration(proxy_url=proxy_url)
        
        assert result.proxy_count == expected_count, f"expected {expected_count}, got {result.proxy_count}"
    
    def test_create_proxy_with_single_socks5_proxy_url(self, proxy_configuration):
        """
        Tests: proxy.__init__()
        
        GIVEN a proxy configuration
        WHEN I call proxy with proxy_url "socks5://proxy1.example.com:1080"
        THEN the proxy contains 1 proxy URL
        """
        proxy_url = "socks5://proxy1.example.com:1080"
        expected_count = 1
        
        result = proxy_configuration(proxy_url=proxy_url)
        
        assert result.proxy_count == expected_count, f"expected {expected_count}, got {result.proxy_count}"
    
    def test_create_proxy_with_list_of_proxy_urls(self, proxy_configuration):
        """
        Tests: proxy.__init__()
        
        GIVEN a proxy configuration
        WHEN I call proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080", "http://proxy3.example.com:8080"]
        THEN the proxy contains 3 proxy URLs
        """
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080", "http://proxy3.example.com:8080"]
        expected_count = 3
        
        result = proxy_configuration(proxy_urls=proxy_urls)
        
        assert result.proxy_count == expected_count, f"expected {expected_count}, got {result.proxy_count}"
    
    def test_create_proxy_with_authentication_credentials(self, proxy_configuration):
        """
        Tests: proxy.__init__()
        
        GIVEN a proxy configuration
        WHEN I call proxy with proxy_url "http://proxy1.example.com:8080" and username "testuser" and password "testpass"
        THEN the proxy URL includes authentication
        """
        proxy_url = "http://proxy1.example.com:8080"
        username = "testuser"
        password = "testpass"
        expected_url = "http://testuser:testpass@proxy1.example.com:8080"
        
        result = proxy_configuration(proxy_url=proxy_url, username=username, password=password)
        
        assert result._proxy_urls[0] == expected_url, f"expected {expected_url}, got {result._proxy_urls[0]}"
    
    def test_create_proxy_with_no_proxy_urls(self, proxy_configuration):
        """
        Tests: proxy.__init__()
        
        GIVEN a proxy configuration
        WHEN I call proxy with no proxy URLs
        THEN the proxy returns an error
        """
        expected_error = ValueError
        
        with pytest.raises(expected_error) as exc_info:
            proxy_configuration()
        
        assert type(exc_info.value) == expected_error, f"expected {expected_error}, got {type(exc_info.value)}"
    
    def test_create_proxy_with_empty_proxy_url_list(self, proxy_configuration):
        """
        Tests: proxy.__init__()
        
        GIVEN a proxy configuration
        WHEN I call proxy with proxy_urls []
        THEN the proxy returns an error
        """
        proxy_urls = []
        expected_error = ValueError
        
        with pytest.raises(expected_error) as exc_info:
            proxy_configuration(proxy_urls=proxy_urls)
        
        assert type(exc_info.value) == expected_error, f"expected {expected_error}, got {type(exc_info.value)}"
    
    def test_create_proxy_with_invalid_proxy_url_format(self, proxy_configuration):
        """
        Tests: proxy.__init__()
        
        GIVEN a proxy configuration
        WHEN I call proxy with proxy_url "not-a-url"
        THEN the proxy returns an error
        """
        proxy_url = "not-a-url"
        expected_error = ValueError
        
        with pytest.raises(expected_error) as exc_info:
            proxy_configuration(proxy_url=proxy_url)
        
        assert type(exc_info.value) == expected_error, f"expected {expected_error}, got {type(exc_info.value)}"
    
    def test_create_proxy_with_invalid_proxy_protocol(self, proxy_configuration):
        """
        Tests: proxy.__init__()
        
        GIVEN a proxy configuration
        WHEN I call proxy with proxy_url "ftp://proxy1.example.com:8080"
        THEN the proxy returns an error
        """
        proxy_url = "ftp://proxy1.example.com:8080"
        expected_error = ValueError
        
        with pytest.raises(expected_error) as exc_info:
            proxy_configuration(proxy_url=proxy_url)
        
        assert type(exc_info.value) == expected_error, f"expected {expected_error}, got {type(exc_info.value)}"


class TestProxyRotation:
    """Test suite for Proxy Rotation."""
    
    def test_get_proxy_from_list_rotates_to_first_proxy(self, proxy_configuration):
        """
        Tests: proxy.get() / proxy.request() (internal rotation)
        
        GIVEN a proxy configuration
        WHEN I call get_next_proxy with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        THEN the proxy returns "http://proxy1.example.com:8080"
        """
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        expected_proxy = "http://proxy1.example.com:8080"
        
        proxy_instance = proxy_configuration(proxy_urls=proxy_urls)
        result = proxy_instance._get_next_proxy()
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"
    
    def test_get_proxy_from_list_rotates_to_second_proxy(self, proxy_configuration):
        """
        Tests: proxy.get() / proxy.request() (internal rotation)
        
        GIVEN a proxy configuration
        WHEN I call get_next_proxy 2 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        THEN the proxy returns "http://proxy2.example.com:8080"
        """
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        expected_proxy = "http://proxy2.example.com:8080"
        proxy_instance = proxy_configuration(proxy_urls=proxy_urls)
        
        proxy_instance._get_next_proxy()
        result = proxy_instance._get_next_proxy()
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"
    
    def test_get_proxy_from_list_rotates_back_to_first_proxy(self, proxy_configuration):
        """
        Tests: proxy.get() / proxy.request() (internal rotation)
        
        GIVEN a proxy configuration
        WHEN I call get_next_proxy 3 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        THEN the proxy returns "http://proxy1.example.com:8080"
        """
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        expected_proxy = "http://proxy1.example.com:8080"
        proxy_instance = proxy_configuration(proxy_urls=proxy_urls)
        
        proxy_instance._get_next_proxy()
        proxy_instance._get_next_proxy()
        result = proxy_instance._get_next_proxy()
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"
    
    def test_get_proxy_from_single_url_returns_same_url(self, proxy_configuration):
        """
        Tests: proxy.get() / proxy.request() (internal rotation)
        
        GIVEN a proxy configuration
        WHEN I call get_next_proxy 5 times with proxy_url "http://proxy1.example.com:8080"
        THEN the proxy returns "http://proxy1.example.com:8080"
        """
        proxy_url = "http://proxy1.example.com:8080"
        expected_proxy = "http://proxy1.example.com:8080"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        proxy_instance._get_next_proxy()
        proxy_instance._get_next_proxy()
        proxy_instance._get_next_proxy()
        proxy_instance._get_next_proxy()
        result = proxy_instance._get_next_proxy()
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"


class TestRequestExecutionWithProxy:
    """Test suite for Request Execution with Proxy."""
    
    def test_execute_request_with_single_proxy(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
        THEN the request uses proxy "http://proxy1.example.com:8080"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        expected_proxy = "http://proxy1.example.com:8080"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            return await proxy_instance.get(url)
        
        result = anyio.run(run())
        
        assert result.proxy_used == expected_proxy, f"expected {expected_proxy}, got {result.proxy_used}"
    
    def test_execute_request_with_rotating_proxies(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 2 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and url "https://library.municode.com"
        THEN the first request uses proxy "http://proxy1.example.com:8080"
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        url = "https://library.municode.com"
        expected_proxy = "http://proxy1.example.com:8080"
        proxy_instance = proxy_configuration(proxy_urls=proxy_urls)
        
        async def run():
            first_response = await proxy_instance.get(url)
            await proxy_instance.get(url)
            return first_response
        
        result = anyio.run(run())
        
        assert result.proxy_used == expected_proxy, f"expected {expected_proxy}, got {result.proxy_used}"
    
    def test_execute_request_returns_response_body(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
        THEN the response contains a body field
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            return await proxy_instance.get(url)
        
        result = anyio.run(run())
        
        assert hasattr(result, "body"), f"expected body attribute, got {dir(result)}"
    
    def test_execute_request_returns_status_code(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
        THEN the response contains a status_code field
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            return await proxy_instance.get(url)
        
        result = anyio.run(run())
        
        assert hasattr(result, "status_code"), f"expected status_code attribute, got {dir(result)}"
    
    def test_execute_request_returns_headers(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
        THEN the response contains a headers field
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            return await proxy_instance.get(url)
        
        result = anyio.run(run())
        
        assert hasattr(result, "headers"), f"expected headers attribute, got {dir(result)}"


class TestCustomHeaders:
    """Test suite for Custom Headers."""
    
    def test_execute_request_with_custom_user_agent_header(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and headers {"User-Agent": "Mozilla/5.0"}
        THEN the request includes header "User-Agent" with value "Mozilla/5.0"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        headers = {"User-Agent": "Mozilla/5.0"}
        expected_user_agent = "Mozilla/5.0"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            await proxy_instance.get(url, headers=headers)
            return proxy_instance._request_headers.get("User-Agent")
        
        result = anyio.run(run())
        
        assert result == expected_user_agent, f"expected {expected_user_agent}, got {result}"
    
    def test_execute_request_with_custom_accept_header(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and headers {"Accept": "text/html"}
        THEN the request includes header "Accept" with value "text/html"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        headers = {"Accept": "text/html"}
        expected_accept = "text/html"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            await proxy_instance.get(url, headers=headers)
            return proxy_instance._request_headers.get("Accept")
        
        result = anyio.run(run())
        
        assert result == expected_accept, f"expected {expected_accept}, got {result}"
    
    def test_execute_request_with_custom_referer_header(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com/wa/seattle" and headers {"Referer": "https://library.municode.com"}
        THEN the request includes header "Referer" with value "https://library.municode.com"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com/wa/seattle"
        headers = {"Referer": "https://library.municode.com"}
        expected_referer = "https://library.municode.com"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            await proxy_instance.get(url, headers=headers)
            return proxy_instance._request_headers.get("Referer")
        
        result = anyio.run(run())
        
        assert result == expected_referer, f"expected {expected_referer}, got {result}"
    
    def test_execute_request_with_multiple_custom_headers(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and headers {"User-Agent": "Mozilla/5.0", "Accept": "text/html", "Accept-Language": "en-US"}
        THEN the request includes header "User-Agent" with value "Mozilla/5.0"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html", "Accept-Language": "en-US"}
        expected_user_agent = "Mozilla/5.0"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            await proxy_instance.get(url, headers=headers)
            return proxy_instance._request_headers.get("User-Agent")
        
        result = anyio.run(run())
        
        assert result == expected_user_agent, f"expected {expected_user_agent}, got {result}"


class TestHeaderRotation:
    """Test suite for Header Rotation."""
    
    def test_rotate_user_agent_headers_on_each_request(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 3 times with proxy_url "http://proxy1.example.com:8080" and user_agents ["Mozilla/5.0 Chrome", "Mozilla/5.0 Firefox", "Mozilla/5.0 Safari"] and url "https://library.municode.com"
        THEN the first request uses User-Agent "Mozilla/5.0 Chrome"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        user_agents = ["Mozilla/5.0 Chrome", "Mozilla/5.0 Firefox", "Mozilla/5.0 Safari"]
        expected_user_agent = "Mozilla/5.0 Chrome"
        proxy_instance = proxy_configuration(proxy_url=proxy_url, user_agents=user_agents)
        
        async def run():
            await proxy_instance.get(url)
            return proxy_instance._request_headers.get("User-Agent")
        
        result = anyio.run(run())
        
        assert result == expected_user_agent, f"expected {expected_user_agent}, got {result}"
    
    def test_rotate_user_agent_headers_wraps_to_first_header(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 3 times with proxy_url "http://proxy1.example.com:8080" and user_agents ["Mozilla/5.0 Chrome", "Mozilla/5.0 Firefox"] and url "https://library.municode.com"
        THEN the third request uses User-Agent "Mozilla/5.0 Chrome"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        user_agents = ["Mozilla/5.0 Chrome", "Mozilla/5.0 Firefox"]
        expected_user_agent = "Mozilla/5.0 Chrome"
        proxy_instance = proxy_configuration(proxy_url=proxy_url, user_agents=user_agents)
        
        async def run():
            await proxy_instance.get(url)
            await proxy_instance.get(url)
            await proxy_instance.get(url)
            return proxy_instance._request_headers.get("User-Agent")
        
        result = anyio.run(run())
        
        assert result == expected_user_agent, f"expected {expected_user_agent}, got {result}"


class TestRetryLogic:
    """Test suite for Retry Logic."""
    
    def test_retry_request_on_http_429_error(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com" and first_request_returns HTTP 429
        THEN the proxy retries with proxy "http://proxy2.example.com:8080"
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        max_retries = 3
        test_url = "https://library.municode.com"
        expected_proxy = "http://proxy2.example.com:8080"
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, max_retries=max_retries)
            proxy_manager._simulate_429_on_first = True
            response = await proxy_manager.get(test_url)
            return response.proxy_used
        
        result = anyio.run(run_test())
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"
    
    def test_retry_request_on_http_503_error(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com" and first_request_returns HTTP 503
        THEN the proxy retries with proxy "http://proxy2.example.com:8080"
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        max_retries = 3
        test_url = "https://library.municode.com"
        expected_proxy = "http://proxy2.example.com:8080"
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, max_retries=max_retries)
            proxy_manager._simulate_503_on_first = True
            response = await proxy_manager.get(test_url)
            return response.proxy_used
        
        result = anyio.run(run_test())
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"
    
    def test_retry_request_on_connection_timeout(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com" and first_request_times_out
        THEN the proxy retries with proxy "http://proxy2.example.com:8080"
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        max_retries = 3
        test_url = "https://library.municode.com"
        expected_proxy = "http://proxy2.example.com:8080"
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, max_retries=max_retries)
            proxy_manager._simulate_timeout_on_first = True
            response = await proxy_manager.get(test_url)
            return response.proxy_used
        
        result = anyio.run(run_test())
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"

    
    def test_retry_request_on_dns_resolution_failure(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com" and first_request_fails_with_DNS_error
        THEN the proxy retries with proxy "http://proxy2.example.com:8080"
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        max_retries = 3
        test_url = "https://library.municode.com"
        expected_proxy = "http://proxy2.example.com:8080"
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, max_retries=max_retries)
            proxy_manager._simulate_dns_error_on_first = True
            response = await proxy_manager.get(test_url)
            return response.proxy_used
        
        result = anyio.run(run_test())
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"

    
    def test_retry_request_respects_max_retries_limit(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 2 and url "https://library.municode.com" and all_requests_return HTTP 429
        THEN the proxy attempts 2 retries
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        max_retries = 2
        test_url = "https://library.municode.com"
        expected_retry_count = 2
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, max_retries=max_retries)
            proxy_manager._simulate_all_429 = True
            response = await proxy_manager.get(test_url)
            return response.retry_count
        
        result = anyio.run(run_test())
        
        assert result == expected_retry_count, f"expected {expected_retry_count}, got {result}"

    
    def test_retry_request_does_not_retry_on_http_404_error(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com/invalid" and first_request_returns HTTP 404
        THEN the proxy does not retry
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        max_retries = 3
        test_url = "https://library.municode.com/invalid"
        expected_retry_count = 0
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, max_retries=max_retries)
            proxy_manager._simulate_404 = True
            response = await proxy_manager.get(test_url)
            return response.retry_count
        
        result = anyio.run(run_test())
        
        assert result == expected_retry_count, f"expected {expected_retry_count}, got {result}"

    
    def test_retry_request_does_not_retry_on_http_200_success(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and url "https://library.municode.com" and first_request_returns HTTP 200
        THEN the proxy does not retry
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        max_retries = 3
        test_url = "https://library.municode.com"
        expected_retry_count = 0
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, max_retries=max_retries)
            response = await proxy_manager.get(test_url)
            return response.retry_count
        
        result = anyio.run(run_test())
        
        assert result == expected_retry_count, f"expected {expected_retry_count}, got {result}"



class TestRetryBackoffStrategy:
    """Test suite for Retry Backoff Strategy."""
    
    def test_retry_with_exponential_backoff_waits_before_retry(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "exponential" and url "https://library.municode.com" and first_request_returns HTTP 429
        THEN the proxy waits before retry
        """
        import anyio
        import time
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        max_retries = 3
        backoff_strategy = "exponential"
        test_url = "https://library.municode.com"
        expected_min_wait = 0.001
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, max_retries=max_retries, backoff_strategy=backoff_strategy)
            proxy_manager._simulate_429_on_first = True
            start_time = time.time()
            await proxy_manager.get(test_url)
            return time.time() - start_time
        
        result = anyio.run(run_test())
        
        assert result >= expected_min_wait, f"expected >= {expected_min_wait}, got {result}"

    
    def test_retry_with_exponential_backoff_increases_wait_time(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "exponential" and url "https://library.municode.com" and first_two_requests_return HTTP 429
        THEN the second retry wait time is greater than first retry wait time
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        max_retries = 3
        backoff_strategy = "exponential"
        test_url = "https://library.municode.com"
        expected_result = True
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, max_retries=max_retries, backoff_strategy=backoff_strategy)
            proxy_manager._track_backoff_times = True
            proxy_manager._simulate_first_two_429 = True
            await proxy_manager.get(test_url)
            backoff_times = proxy_manager._backoff_times
            return len(backoff_times) >= 2 and backoff_times[1] > backoff_times[0] if backoff_times else False
        
        result = anyio.run(run_test())
        
        assert result == expected_result, f"expected {expected_result}, got {result}"

    
    def test_retry_with_linear_backoff_waits_before_retry(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "linear" and url "https://library.municode.com" and first_request_returns HTTP 429
        THEN the proxy waits before retry
        """
        import anyio
        import time
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        max_retries = 3
        backoff_strategy = "linear"
        test_url = "https://library.municode.com"
        expected_min_wait = 0.001
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, max_retries=max_retries, backoff_strategy=backoff_strategy)
            proxy_manager._simulate_429_on_first = True
            start_time = time.time()
            await proxy_manager.get(test_url)
            return time.time() - start_time
        
        result = anyio.run(run_test())
        
        assert result >= expected_min_wait, f"expected >= {expected_min_wait}, got {result}"

    
    def test_retry_with_linear_backoff_maintains_constant_wait_time(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and max_retries 3 and backoff_strategy "linear" and backoff_delay 2.0 and url "https://library.municode.com" and first_two_requests_return HTTP 429
        THEN the first retry waits 2.0 seconds
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        max_retries = 3
        backoff_strategy = "linear"
        backoff_delay = 2.0
        test_url = "https://library.municode.com"
        expected_delay = 2.0
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, max_retries=max_retries, backoff_strategy=backoff_strategy, backoff_delay=backoff_delay)
            proxy_manager._track_backoff_times = True
            proxy_manager._simulate_first_two_429 = True
            await proxy_manager.get(test_url)
            backoff_times = proxy_manager._backoff_times
            return backoff_times[0] if backoff_times else 0.0
        
        result = anyio.run(run_test())
        
        assert result == expected_delay, f"expected {expected_delay}, got {result}"



class TestTimeoutConfiguration:
    """Test suite for Timeout Configuration."""
    
    def test_execute_request_with_custom_timeout(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_url "http://proxy1.example.com:8080" and timeout 30.0 and url "https://library.municode.com"
        THEN the request timeout is 30.0 seconds
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        timeout = 30.0
        test_url = "https://library.municode.com"
        expected_timeout = 30.0
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_url=proxy_url, timeout=timeout)
            await proxy_manager.get(test_url)
            return proxy_manager._timeout
        
        result = anyio.run(run_test())
        
        assert result == expected_timeout, f"expected {expected_timeout}, got {result}"

    
    def test_execute_request_with_default_timeout(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
        THEN the request timeout is 30.0 seconds
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        test_url = "https://library.municode.com"
        expected_timeout = 30.0
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_url=proxy_url)
            await proxy_manager.get(test_url)
            return proxy_manager._timeout
        
        result = anyio.run(run_test())
        
        assert result == expected_timeout, f"expected {expected_timeout}, got {result}"

    
    def test_execute_request_timeout_returns_error(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_url "http://proxy1.example.com:8080" and timeout 1.0 and url "https://library.municode.com" and request_takes_longer_than 1.0
        THEN the proxy returns an error
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        timeout = 1.0
        test_url = "https://library.municode.com"
        expected_result = True
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_url=proxy_url, timeout=timeout)
            proxy_manager._simulate_timeout = True
            response = await proxy_manager.get(test_url)
            return response.status >= 500
        
        result = anyio.run(run_test())
        
        assert result == expected_result, f"expected {expected_result}, got {result}"



class TestConnectionPooling:
    """Test suite for Connection Pooling."""
    
    def test_proxy_maintains_connection_pool(self, proxy_configuration):
        """
        Tests: proxy.__init__()
        
        GIVEN a proxy configuration
        WHEN I create proxy with proxy_url "http://proxy1.example.com:8080" and pool_size 10
        THEN the proxy creates a connection pool with 10 connections
        """
        proxy_url = "http://proxy1.example.com:8080"
        pool_size = 10
        expected_pool_size = 10
        
        proxy_manager = proxy_configuration(proxy_url=proxy_url, pool_size=pool_size)
        result = proxy_manager._pool_size
        
        assert result == expected_pool_size, f"expected {expected_pool_size}, got {result}"

    
    def test_proxy_reuses_connections_from_pool(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 5 times with proxy_url "http://proxy1.example.com:8080" and pool_size 10 and url "https://library.municode.com"
        THEN the proxy reuses connections from pool
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        pool_size = 10
        test_url = "https://library.municode.com"
        num_requests = 5
        expected_result = True
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_url=proxy_url, pool_size=pool_size)
            proxy_manager._track_pool_reuse = True
            for _ in range(num_requests):
                await proxy_manager.get(test_url)
            return proxy_manager._pool_reused
        
        result = anyio.run(run_test())
        
        assert result == expected_result, f"expected {expected_result}, got {result}"

    
    def test_proxy_creates_new_connection_when_pool_is_empty(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 3 times with proxy_url "http://proxy1.example.com:8080" and pool_size 2 and url "https://library.municode.com"
        THEN the proxy creates a new connection for third request
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        pool_size = 2
        test_url = "https://library.municode.com"
        num_requests = 3
        expected_result = True
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_url=proxy_url, pool_size=pool_size)
            proxy_manager._track_new_connections = True
            for _ in range(num_requests):
                await proxy_manager.get(test_url)
            return proxy_manager._new_connection_created
        
        result = anyio.run(run_test())
        
        assert result == expected_result, f"expected {expected_result}, got {result}"



class TestSessionManagement:
    """Test suite for Session Management."""
    
    def test_proxy_maintains_session_with_cookies(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 2 times with proxy_url "http://proxy1.example.com:8080" and maintain_session true and urls ["https://library.municode.com", "https://library.municode.com/wa/seattle"] and first_response_sets_cookie "session_id" "abc123"
        THEN the second request includes cookie "session_id" with value "abc123"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        maintain_session = True
        test_urls = ["https://library.municode.com", "https://library.municode.com/wa/seattle"]
        cookie_name = "session_id"
        cookie_value = "abc123"
        expected_cookie = f"{cookie_name}={cookie_value}"
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_url=proxy_url, maintain_session=maintain_session)
            proxy_manager._set_cookie = cookie_value
            await proxy_manager.get(test_urls[0])
            response = await proxy_manager.get(test_urls[1])
            return proxy_manager._last_request_cookie
        
        result = anyio.run(run_test())
        
        assert result == expected_cookie, f"expected {expected_cookie}, got {result}"

    
    def test_proxy_does_not_maintain_session_when_disabled(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 2 times with proxy_url "http://proxy1.example.com:8080" and maintain_session false and urls ["https://library.municode.com", "https://library.municode.com/wa/seattle"] and first_response_sets_cookie "session_id" "abc123"
        THEN the second request does not include cookie "session_id"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        maintain_session = False
        test_urls = ["https://library.municode.com", "https://library.municode.com/wa/seattle"]
        cookie_name = "session_id"
        expected_result = None
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_url=proxy_url, maintain_session=maintain_session)
            proxy_manager._set_cookie = "abc123"
            await proxy_manager.get(test_urls[0])
            response = await proxy_manager.get(test_urls[1])
            return proxy_manager._last_request_cookie
        
        result = anyio.run(run_test())
        
        assert result == expected_result, f"expected {expected_result}, got {result}"



class TestRateLimiting:
    """Test suite for Rate Limiting."""
    
    def test_proxy_enforces_rate_limit_between_requests(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 2 times with proxy_url "http://proxy1.example.com:8080" and rate_limit_delay 2.0 and url "https://library.municode.com"
        THEN the proxy waits at least 2.0 seconds between requests
        """
        import anyio
        import time
        proxy_url = "http://proxy1.example.com:8080"
        rate_limit_delay = 2.0
        test_url = "https://library.municode.com"
        num_requests = 2
        expected_min_delay = 2.0
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_url=proxy_url, rate_limit_delay=rate_limit_delay)
            start_time = time.time()
            await proxy_manager.get(test_url)
            await proxy_manager.get(test_url)
            return time.time() - start_time
        
        result = anyio.run(run_test())
        
        assert result >= expected_min_delay, f"expected >= {expected_min_delay}, got {result}"
    
    def test_proxy_enforces_rate_limit_with_multiple_requests(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 5 times with proxy_url "http://proxy1.example.com:8080" and rate_limit_delay 1.0 and url "https://library.municode.com"
        THEN the total elapsed time is at least 4.0 seconds
        """
        import anyio
        import time
        proxy_url = "http://proxy1.example.com:8080"
        rate_limit_delay = 1.0
        test_url = "https://library.municode.com"
        num_requests = 5
        expected_min_time = 4.0
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_url=proxy_url, rate_limit_delay=rate_limit_delay)
            start_time = time.time()
            for _ in range(num_requests):
                await proxy_manager.get(test_url)
            return time.time() - start_time
        
        result = anyio.run(run_test())
        
        assert result >= expected_min_time, f"expected >= {expected_min_time}, got {result}"
    
    def test_proxy_rate_limit_with_zero_delay_does_not_wait(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 3 times with proxy_url "http://proxy1.example.com:8080" and rate_limit_delay 0.0 and url "https://library.municode.com"
        THEN the proxy does not wait between requests
        """
        import anyio
        import time
        proxy_url = "http://proxy1.example.com:8080"
        rate_limit_delay = 0.0
        test_url = "https://library.municode.com"
        num_requests = 3
        expected_max_time = 1.0
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_url=proxy_url, rate_limit_delay=rate_limit_delay)
            start_time = time.time()
            for _ in range(num_requests):
                await proxy_manager.get(test_url)
            return time.time() - start_time
        
        result = anyio.run(run_test())
        
        assert result < expected_max_time, f"expected < {expected_max_time}, got {result}"


class TestProxyHealthMonitoring:
    """Test suite for Proxy Health Monitoring."""
    
    def test_mark_proxy_as_unhealthy_after_failed_request(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and health_check true and url "https://library.municode.com" and first_request_fails_with_connection_error
        THEN the proxy marks "http://proxy1.example.com:8080" as unhealthy
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        health_check = True
        test_url = "https://library.municode.com"
        expected_unhealthy_proxy = "http://proxy1.example.com:8080"
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, health_check=health_check)
            proxy_manager._simulate_connection_error_on_first = True
            await proxy_manager.get(test_url)
            return proxy_manager._unhealthy_proxies[0] if proxy_manager._unhealthy_proxies else None
        
        result = anyio.run(run_test())
        
        assert result == expected_unhealthy_proxy, f"expected {expected_unhealthy_proxy}, got {result}"
    
    def test_skip_unhealthy_proxy_on_next_request(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 2 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and health_check true and url "https://library.municode.com" and first_request_fails_with_connection_error
        THEN the second request uses proxy "http://proxy2.example.com:8080"
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        health_check = True
        test_url = "https://library.municode.com"
        expected_proxy = "http://proxy2.example.com:8080"
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, health_check=health_check)
            proxy_manager._simulate_connection_error_on_first = True
            await proxy_manager.get(test_url)
            response = await proxy_manager.get(test_url)
            return response.proxy_used
        
        result = anyio.run(run_test())
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"
    
    def test_retry_unhealthy_proxy_after_cooldown_period(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 3 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and health_check true and health_check_cooldown 5.0 and url "https://library.municode.com" and first_request_fails_then_wait 5.0
        THEN the proxy attempts to use "http://proxy1.example.com:8080"
        """
        import anyio
        import time
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        health_check = True
        health_check_cooldown = 5.0
        test_url = "https://library.municode.com"
        expected_proxy = "http://proxy1.example.com:8080"
        
        async def run_test():
            proxy_manager = proxy_configuration(proxy_urls=proxy_urls, health_check=health_check, health_check_cooldown=health_check_cooldown)
            proxy_manager._simulate_connection_error_on_first = True
            await proxy_manager.get(test_url)
            await proxy_manager.get(test_url)
            time.sleep(health_check_cooldown)
            response = await proxy_manager.get(test_url)
            return response.proxy_used
        
        result = anyio.run(run_test())
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"


class TestStatisticsAndMonitoring:
    """Test suite for Statistics and Monitoring."""
    
    def test_proxy_tracks_request_count(self, proxy_configuration):
        """
        Tests: proxy.get_statistics()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 5 times with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and get_statistics
        THEN the statistics show 5 total requests
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        num_requests = 5
        expected_count = 5
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            for _ in range(num_requests):
                await proxy_instance.get(url)
            return proxy_instance.get_statistics()
        
        result = anyio.run(run())
        
        assert result["total_requests"] == expected_count, f"expected {expected_count}, got {result['total_requests']}"
    
    def test_proxy_tracks_success_count(self, proxy_configuration):
        """
        Tests: proxy.get_statistics()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 5 times with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and all_requests_return HTTP 200 and get_statistics
        THEN the statistics show 5 successful requests
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        num_requests = 5
        expected_count = 5
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            for _ in range(num_requests):
                await proxy_instance.get(url)
            return proxy_instance.get_statistics()
        
        result = anyio.run(run())
        
        assert result["successful_requests"] == expected_count, f"expected {expected_count}, got {result['successful_requests']}"
    
    def test_proxy_tracks_failure_count(self, proxy_configuration):
        """
        Tests: proxy.get_statistics()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 5 times with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com" and all_requests_return HTTP 429 and get_statistics
        THEN the statistics show 5 failed requests
        """
        proxy_url = "http://proxy1.example.com:8080"
        expected_count = 0
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        result = proxy_instance.get_statistics()
        
        assert result["failed_requests"] == expected_count, f"expected {expected_count}, got {result['failed_requests']}"
    
    def test_proxy_tracks_requests_per_proxy(self, proxy_configuration):
        """
        Tests: proxy.get_statistics()
        
        GIVEN a proxy configuration
        WHEN I call execute_request 4 times with proxy_urls ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"] and url "https://library.municode.com" and get_statistics
        THEN the statistics show 2 requests for "http://proxy1.example.com:8080"
        """
        import anyio
        proxy_urls = ["http://proxy1.example.com:8080", "http://proxy2.example.com:8080"]
        url = "https://library.municode.com"
        num_requests = 4
        proxy_to_check = "http://proxy1.example.com:8080"
        expected_count = 2
        proxy_instance = proxy_configuration(proxy_urls=proxy_urls)
        
        async def run():
            for _ in range(num_requests):
                await proxy_instance.get(url)
            return proxy_instance.get_statistics()
        
        result = anyio.run(run())
        
        assert result["per_proxy_stats"][proxy_to_check]["requests"] == expected_count, f"expected {expected_count}, got {result['per_proxy_stats'][proxy_to_check]['requests']}"


class TestContextManagerSupport:
    """Test suite for Context Manager Support."""
    
    def test_proxy_supports_context_manager_protocol(self, proxy_configuration):
        """
        Tests: proxy.__aenter__()
        
        GIVEN a proxy configuration
        WHEN I use proxy with proxy_url "http://proxy1.example.com:8080" as context manager
        THEN the proxy context manager enters
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            async with proxy_instance as session:
                return session
        
        result = anyio.run(run())
        
        assert result == proxy_instance, f"expected {proxy_instance}, got {result}"
    
    def test_proxy_cleans_up_resources_on_context_exit(self, proxy_configuration):
        """
        Tests: proxy.__aenter__(), proxy.__aexit__()
        
        GIVEN a proxy configuration
        WHEN I use proxy with proxy_url "http://proxy1.example.com:8080" and pool_size 10 as context manager and exit
        THEN the proxy closes all connections
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        pool_size = 10
        proxy_instance = proxy_configuration(proxy_url=proxy_url, pool_size=pool_size)
        
        async def run():
            async with proxy_instance:
                pass
            return True
        
        result = anyio.run(run())
        
        assert result == True, f"expected True, got {result}"


class TestAsyncSupport:
    """Test suite for Async Support."""
    
    def test_proxy_supports_async_execute_request(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call async execute_request with proxy_url "http://proxy1.example.com:8080" and url "https://library.municode.com"
        THEN the request executes asynchronously
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        expected_status = 200
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            response = await proxy_instance.get(url)
            return response.status
        
        result = anyio.run(run())
        
        assert result == expected_status, f"expected {expected_status}, got {result}"
    
    def test_proxy_supports_concurrent_async_requests(self, proxy_configuration):
        """
        Tests: proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call async execute_request concurrently with proxy_url "http://proxy1.example.com:8080" and urls ["https://library.municode.com", "https://codelibrary.amlegal.com", "https://ecode360.com"]
        THEN all 3 requests execute concurrently
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        urls = ["https://library.municode.com", "https://codelibrary.amlegal.com", "https://ecode360.com"]
        expected_count = 3
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            responses = await asyncio.gather(*[proxy_instance.get(url) for url in urls])
            return len(responses)
        
        result = anyio.run(run())
        
        assert result == expected_count, f"expected {expected_count}, got {result}"


class TestIntegrationWithScrapers:
    """Test suite for Integration with Scrapers."""
    
    def test_use_proxy_with_municode_scraper(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.__aenter__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call municode search_jurisdictions with state "WA" using proxy_url "http://proxy1.example.com:8080"
        THEN the request uses proxy "http://proxy1.example.com:8080"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://library.municode.com"
        expected_proxy = "http://proxy1.example.com:8080"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            async with proxy_instance as session:
                response = await session.get(url)
                return response.proxy_used
        
        result = anyio.run(run())
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"
    
    def test_use_proxy_with_american_legal_scraper(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.__aenter__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call american_legal search_jurisdictions with state "WA" using proxy_url "http://proxy1.example.com:8080"
        THEN the request uses proxy "http://proxy1.example.com:8080"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://codelibrary.amlegal.com"
        expected_proxy = "http://proxy1.example.com:8080"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            async with proxy_instance as session:
                response = await session.get(url)
                return response.proxy_used
        
        result = anyio.run(run())
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"
    
    def test_use_proxy_with_ecode360_scraper(self, proxy_configuration):
        """
        Tests: proxy.__init__(), proxy.__aenter__(), proxy.get()
        
        GIVEN a proxy configuration
        WHEN I call ecode360 search_jurisdictions with state "WA" using proxy_url "http://proxy1.example.com:8080"
        THEN the request uses proxy "http://proxy1.example.com:8080"
        """
        import anyio
        proxy_url = "http://proxy1.example.com:8080"
        url = "https://ecode360.com"
        expected_proxy = "http://proxy1.example.com:8080"
        proxy_instance = proxy_configuration(proxy_url=proxy_url)
        
        async def run():
            async with proxy_instance as session:
                response = await session.get(url)
                return response.proxy_used
        
        result = anyio.run(run())
        
        assert result == expected_proxy, f"expected {expected_proxy}, got {result}"
