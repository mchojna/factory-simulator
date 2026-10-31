"""The MkDocs hook that excludes the collection README from localized collections.

Examples:
    >>> is_collection_readme("README.md")
    True
"""

from mkdocs.structure.files import Files


def is_collection_readme(source_path: str) -> bool:
    """Tell whether a source path is the collection README.

    Args:
        source_path (str): The path relative to the documentation directory.

    Returns:
        bool: True when the path is the collection README.

    Examples:
        >>> is_collection_readme("README.md")
        True
        >>> is_collection_readme("en/README.md")
        False
    """
    return source_path == "README.md"


def on_files(files: Files, **_arguments: object) -> Files:
    """Remove the collection README before the language folder plugin resolves pages.

    Args:
        files (Files): The files discovered by MkDocs.
        _arguments (object): Other values supplied by the MkDocs event.

    Returns:
        Files: The files without the collection README.

    Examples:
        >>> from mkdocs.structure.files import File
        >>> files = Files(
        ...     [
        ...         File("README.md", "docs", "site", False),
        ...         File("en/README.md", "docs", "site", False),
        ...     ]
        ... )
        >>> [file.src_uri for file in on_files(files)]
        ['en/README.md']
    """
    for file in list(files):
        if is_collection_readme(file.src_uri):
            files.remove(file)
    return files
