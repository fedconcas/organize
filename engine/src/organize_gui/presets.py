from typing import Any, Dict, List


CATEGORIES = {
    "documents": {
        "label": "Documents",
        "extensions": [
            "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md", "csv"
        ],
    },
    "images": {
        "label": "Images",
        "extensions": ["jpg", "jpeg", "png", "gif", "webp", "heic", "tif", "tiff"],
    },
    "videos": {
        "label": "Videos",
        "extensions": ["mp4", "mov", "mkv", "avi", "webm", "m4v"],
    },
    "audio": {
        "label": "Audio",
        "extensions": ["mp3", "m4a", "wav", "flac", "aac", "ogg"],
    },
    "archives": {
        "label": "Archives",
        "extensions": ["zip", "7z", "rar", "tar", "gz", "bz2", "xz"],
    },
    "installers": {
        "label": "Installers",
        "extensions": ["exe", "msi", "msix", "dmg", "pkg"],
    },
    "other": {"label": "Other files", "extensions": []},
}

IMAGE_EXTENSIONS = set(CATEGORIES["images"]["extensions"])
INSTALLER_EXTENSIONS = {"exe", "msi", "msix", "dmg", "pkg"}


def all_presets() -> List[Dict[str, Any]]:
    return [
        {
            "id": "by-type",
            "name": "Organize files by type",
            "description": "Documents, images, videos and more each go to one place.",
            "operation": "move",
        },
        {
            "id": "by-date",
            "name": "Archive images by date",
            "description": "Organizes photos and screenshots by year and month.",
            "operation": "move",
        },
        {
            "id": "old-installers",
            "name": "Clean up old installers",
            "description": "Free up space taken by old installers.",
            "operation": "quarantine",
        },
        {
            "id": "duplicates",
            "name": "Duplicate file finder",
            "description": "Only byte-for-byte identical content counts as a duplicate.",
            "operation": "quarantine",
        },
        {
            "id": "similar-photos",
            "name": "Similar photos",
            "description": "Finds identical and similar-looking photos, including rotated or flipped copies.",
            "operation": "quarantine",
        },
    ]


def category_for_extension(extension: str, enabled: List[str]) -> str:
    normalized = extension.casefold().lstrip(".")
    for key in enabled:
        category = CATEGORIES.get(key)
        if category and normalized in category["extensions"]:
            return key
    return "other" if "other" in enabled else ""
