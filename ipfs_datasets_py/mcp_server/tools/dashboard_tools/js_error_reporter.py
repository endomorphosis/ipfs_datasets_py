#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JavaScript Error Reporter Tool for MCP Dashboard

Business logic has been extracted to the canonical package module:
    ipfs_datasets_py/processors/dashboard/js_error_reporter_engine.py

This file is now a thin re-export shim so existing imports continue to work.
"""
import sys

from ipfs_datasets_py.processors.dashboard.js_error_reporter_engine import (  # noqa: F401
    JavaScriptErrorReporter,
    get_js_error_reporter,
    GitHubIssueClient,
    coordinate_auto_healing,
)

# Allow patching/consuming this module via either import path.
_this_module = sys.modules.get(__name__)
if _this_module is not None:
    _this_module.JavaScriptErrorReporter = JavaScriptErrorReporter
    _this_module.get_js_error_reporter = get_js_error_reporter
