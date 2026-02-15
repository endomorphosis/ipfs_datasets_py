from typing import Optional
from pydantic import BaseModel


class ProxyLaunchConfigs(BaseModel):
    """
    Network proxy settings configuration for a Chromium-based browser in Playwright.
    See: https://playwright.dev/python/docs/api/class-browsertype for more details.
    
    Attributes:
        server (str): Proxy to be used for all requests. HTTP and SOCKS proxies are supported, 
            for example `http://myproxy.com:3128` or `socks5://myproxy.com:3128`. 
            Short form `myproxy.com:3128` is considered an HTTP proxy.
        bypass (Optional[str]): Optional comma-separated domains to bypass proxy,
                for example "`.com, chromium.org, .domain.com`"
        username (Optional[str]): Optional username to use if HTTP proxy requires authentication.
        password (Optional[str]): Optional password to use if HTTP proxy requires authentication.
    """
    server: str
    bypass: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None