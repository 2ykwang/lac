"""Per-slug metadata (.lac.meta) in YAML."""

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Self

import yaml


@dataclass
class Meta:
    """Per-slug metadata stored as YAML in `.lac.meta`.

    Machine-invariant only — synced across machines via lac home's git repo.
    The machine-local repo path lives in `<slug>/.lac.local` (gitignored), not
    here, so syncing never produces path conflicts.
    """

    repo_remote: str | None = None
    linked_files: list[str] = field(default_factory=list)
    unlinked_files: list[str] = field(default_factory=list)
    created_at: str = ""
    lac_version: str = "0.0.1"

    @classmethod
    def load(cls, path: Path | str) -> Self:
        """Load metadata from path.

        Unknown keys (e.g. the legacy machine-local `repo_path`, now moved to
        `.lac.local`) are ignored so pre-migration files load cleanly.

        Args:
            path: Path to the `.lac.meta` file.

        Returns:
            Meta instance populated from the file.

        Raises:
            FileNotFoundError: The file does not exist.
            yaml.YAMLError: The file content is not parseable YAML.
            TypeError: The parsed content does not match the schema.
        """
        data = yaml.safe_load(Path(path).read_text()) or {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def load_safe(cls, path: Path | str) -> Self | None:
        """Load metadata or return None on missing / unparseable / schema mismatch.

        Args:
            path: Path to the `.lac.meta` file.

        Returns:
            Meta instance on success, None otherwise.
        """
        try:
            return cls.load(path)
        except (FileNotFoundError, yaml.YAMLError, TypeError):
            return None

    def save(self, path: Path | str) -> None:
        """Write the metadata to path as YAML.

        Args:
            path: Destination path for the `.lac.meta` file.
        """
        Path(path).write_text(yaml.safe_dump(asdict(self), sort_keys=False, allow_unicode=True))
