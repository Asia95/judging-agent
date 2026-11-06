"""
drive/fake.py — an in-memory Drive for scenarios and tests (no credentials).
"""

from dataclasses import dataclass, field

from judging_agent.drive.base import FOLDER_MIME, TEXT_MIME


@dataclass
class FakeNode:
    name: str
    parent: str | None
    is_folder: bool = False
    content: str = ""
    owner: str = "owner@company.com"
    mime: str = TEXT_MIME       # ignored for folders


@dataclass
class FakeDrive:
    """DriveBackend over a dict of {id: FakeNode}. Tracks writes for assertions."""
    nodes: dict[str, FakeNode]
    writes: list[tuple[str, str]] = field(default_factory=list)

    def _node(self, resource_id: str) -> FakeNode:
        if resource_id not in self.nodes:
            raise FileNotFoundError(f"File not found: {resource_id}")
        return self.nodes[resource_id]

    def list_folder(self, folder_id: str, max_results: int = 50) -> list[dict]:
        self._node(folder_id)
        children = [
            {"id": nid, "name": n.name, "mimeType": FOLDER_MIME if n.is_folder else n.mime}
            for nid, n in self.nodes.items() if n.parent == folder_id
        ]
        return children[:max_results]

    def read_file(self, file_id: str) -> dict:
        node = self._node(file_id)
        return {"id": file_id, "name": node.name, "content": node.content}

    def update_file(self, file_id: str, content: str) -> dict:
        node = self._node(file_id)
        node.content = content
        self.writes.append((file_id, content))
        return {"id": file_id, "name": node.name, "updated": True}

    def create_file(self, folder_id: str, name: str, content: str) -> dict:
        self._node(folder_id)
        file_id = f"file-created-{len(self.nodes)}-".ljust(28, "0")
        self.nodes[file_id] = FakeNode(name, folder_id, content=content)
        self.writes.append((file_id, content))
        return {"id": file_id, "name": name, "created": True}

    def get_metadata(self, resource_id: str) -> dict | None:
        node = self.nodes.get(resource_id)
        if node is None:
            return None
        # Like Google Drive, the root folder ("My Drive") is not part of the path.
        names, current = [node.name], node.parent
        while current is not None and self.nodes[current].parent is not None:
            names.append(self.nodes[current].name)
            current = self.nodes[current].parent
        return {
            "id": resource_id,
            "name": node.name,
            "path": "/" + "/".join(reversed(names)),
            "owner": node.owner,
            "mimeType": FOLDER_MIME if node.is_folder else node.mime,
            "is_folder": node.is_folder,
        }
