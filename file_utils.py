import os


def unique_filename(filename: str, used_names: set) -> str:
    """ZIP을 풀 때 덮어쓰지 않도록 대소문자까지 고려해 중복을 피합니다."""
    stem, suffix = os.path.splitext(filename)
    candidate = filename
    index = 2
    while candidate.casefold() in used_names:
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    used_names.add(candidate.casefold())
    return candidate
