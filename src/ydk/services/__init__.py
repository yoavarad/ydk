"""YDK services — external integrations behind Protocol interfaces."""

from ydk.services.git import LocalGitService
from ydk.services.protocols import GitService, RemoteService
from ydk.services.remote import GitHubRemoteService, GitLabRemoteService

__all__ = [
    "GitHubRemoteService",
    "GitLabRemoteService",
    "GitService",
    "LocalGitService",
    "RemoteService",
]
