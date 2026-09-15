import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WalkError:
    path: Path
    error: OSError


WalkItem = Path | WalkError


def walk_source(root: Path) -> Iterator[WalkItem]:
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                children = list(entries)
        except OSError as exc:
            yield WalkError(directory, exc)
            continue
        for entry in reversed(children):
            path = Path(entry.path)
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    yield path
            except OSError as exc:
                yield WalkError(path, exc)
