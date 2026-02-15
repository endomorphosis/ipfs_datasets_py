

from typing import Dict, List, Optional, Union
from pathlib import Path
from pydantic import BaseModel, Field

from .proxy_launch_configs import ProxyLaunchConfigs


class BrowserLaunchConfigs(BaseModel):
    """
    Configuration for launching a browser instance in Playwright.
    See: https://playwright.dev/python/docs/api/class-browsertype
    
    Attributes:
        args: Additional arguments to pass to the browser instance. 
              Warning: Use custom browser args at your own risk.
        channel: Browser distribution channel. Use 'chromium' for new headless mode. 
                 Other options include chrome variants and msedge variants.
        chromium_sandbox: Enable Chromium sandboxing.
        devtools: Deprecated. Use debugging tools instead. 
                  Chromium-only option to auto-open Developer Tools panel for each tab.
        downloads_path: Directory for accepted downloads. Temporary directory is created if not specified.
        env: Environment variables visible to the browser.
        executable_path: Path to a browser executable to run instead of the bundled one.
        firefox_user_prefs: Firefox user preferences for about:config.
        handle_sighup: Close the browser process on SIGHUP.
        handle_sigint: Close the browser process on Ctrl-C.
        handle_sigterm: Close the browser process on SIGTERM.
        headless: Whether to run browser in headless mode.
        ignore_default_args: If true, only use args from args parameter. If list, filter out given default arguments.
        proxy: Network proxy settings.
        slow_mo: Slows down Playwright operations by specified milliseconds.
        timeout: Maximum time in milliseconds to wait for browser instance to start.
        traces_dir: Directory where traces are saved.
    """
    
    args: Optional[List[str]] = None
    channel: Optional[str] = None
    chromium_sandbox: Optional[bool] = False
    devtools: Optional[bool] = None
    downloads_path: Optional[Union[str, Path]] = None
    env: Optional[Dict[str, Union[str, float, bool]]] = None
    executable_path: Optional[Union[str, Path]] = None
    firefox_user_prefs: Optional[Dict[str, Union[str, float, bool]]] = None
    handle_sighup: Optional[bool] = True
    handle_sigint: Optional[bool] = True
    handle_sigterm: Optional[bool] = True
    headless: Optional[bool] = True
    ignore_default_args: Optional[Union[bool, List[str]]] = False
    proxy: Optional[ProxyLaunchConfigs] = None
    slow_mo: Optional[float] = None
    timeout: Optional[float] = 30000
    traces_dir: Optional[Union[str, Path]] = None
