#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Issue Client for Error Reporting

This module provides a client for creating GitHub issues from error reports.
"""

import os
import subprocess
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class GitHubIssueClient:
    """Client for creating GitHub issues via GitHub CLI."""
    
    def __init__(
        self, 
        repo: Optional[str] = None,
        github_token: Optional[str] = None
    ):
        """
        Initialize GitHub issue client.
        
        Args:
            repo: GitHub repository in format 'owner/repo'. 
                  Defaults to 'endomorphosis/ipfs_datasets_py'
            github_token: GitHub token for authentication.
                         Defaults to GITHUB_TOKEN or GH_TOKEN env vars.
        """
        self.repo = repo or os.environ.get('GITHUB_REPOSITORY', 'endomorphosis/ipfs_datasets_py')
        self.github_token = github_token or os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
        
    def is_available(self) -> bool:
        """
        Check if GitHub CLI is available and authenticated.
        
        Returns:
            True if gh CLI is available and authenticated
        """
        try:
            # Check if gh is installed
            result = subprocess.run(
                ['gh', '--version'],
                capture_output=True,
                timeout=5
            )
            if result.returncode != 0:
                logger.debug("GitHub CLI not found")
                return False
            
            # Check if authenticated
            env = os.environ.copy()
            if self.github_token:
                env['GH_TOKEN'] = self.github_token
                
            result = subprocess.run(
                ['gh', 'auth', 'status'],
                capture_output=True,
                timeout=5,
                env=env
            )
            
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"GitHub CLI availability check failed: {e}")
            return False
    
    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Create a GitHub issue.
        
        Args:
            title: Issue title
            body: Issue body/description
            labels: List of label names to add
            
        Returns:
            Dictionary with issue creation result
        """
        if not self.is_available():
            return {
                'success': False,
                'error': 'GitHub CLI not available or not authenticated'
            }
        
        try:
            # Prepare command
            cmd = [
                'gh', 'issue', 'create',
                '--repo', self.repo,
                '--title', title,
                '--body', body
            ]
            
            # Add labels if provided
            if labels:
                for label in labels:
                    cmd.extend(['--label', label])
            
            # Set up environment with token
            env = os.environ.copy()
            if self.github_token:
                env['GH_TOKEN'] = self.github_token
            
            # Execute command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env=env
            )
            
            if result.returncode == 0:
                issue_url = result.stdout.strip()
                issue_number = issue_url.split('/')[-1] if issue_url else None
                
                return {
                    'success': True,
                    'issue_url': issue_url,
                    'issue_number': issue_number
                }
            else:
                return {
                    'success': False,
                    'error': f"Issue creation failed: {result.stderr}",
                    'returncode': result.returncode
                }
                
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Issue creation timed out'
            }
        except Exception as e:
            logger.error(f"Failed to create GitHub issue: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def search_issues(
        self,
        query: str,
        state: str = 'open',
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search for existing issues.
        
        Args:
            query: Search query
            state: Issue state (open, closed, all)
            limit: Maximum number of results
            
        Returns:
            List of matching issues
        """
        if not self.is_available():
            return []
        
        try:
            cmd = [
                'gh', 'issue', 'list',
                '--repo', self.repo,
                '--search', query,
                '--state', state,
                '--limit', str(limit),
                '--json', 'number,title,url,state,labels'
            ]
            
            env = os.environ.copy()
            if self.github_token:
                env['GH_TOKEN'] = self.github_token
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env=env
            )
            
            if result.returncode == 0:
                return json.loads(result.stdout)
            else:
                logger.error(f"Issue search failed: {result.stderr}")
                return []
                
        except Exception as e:
            logger.error(f"Failed to search GitHub issues: {e}")
            return []
