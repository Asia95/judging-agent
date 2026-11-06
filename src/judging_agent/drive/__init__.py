"""Drive backends: storage access only, no security logic."""

from judging_agent.drive.base import DriveBackend, ResourceMeta
from judging_agent.drive.dry_run import DryRunDrive
from judging_agent.drive.fake import FakeDrive, FakeNode
from judging_agent.drive.google import GoogleDrive

__all__ = ["DriveBackend", "DryRunDrive", "FakeDrive", "FakeNode", "GoogleDrive", "ResourceMeta"]
