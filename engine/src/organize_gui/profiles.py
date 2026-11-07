import re
from datetime import date
from typing import Any, Dict, List, Tuple

from .presets import CATEGORIES


def valid_folder_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value.strip() not in {".", ".."}
        and len(value) <= 120
        and not any(char in value for char in '/\\<>:"|?*')
        and not any(ord(char) < 32 for char in value)
        and not value.endswith((".", " "))
    )


RULE_KINDS = {"extension", "metadata", "content"}


def _iso_date(value: Any) -> bool:
    try:
        date.fromisoformat(str(value)[:10])
        return True
    except ValueError:
        return False


def valid_match(match: Any) -> bool:
    """Metadata rule match: {isScreenshot?, hasCamera?, isScan?, minPixels?, dateTakenRange?} or {anyOf: [...]}."""
    if not isinstance(match, dict):
        return False
    if "anyOf" in match:
        options = match["anyOf"]
        return len(match) == 1 and isinstance(options, list) and bool(options) and all(
            valid_match(option) and "anyOf" not in option for option in options)
    if set(match) - {"isScreenshot", "hasCamera", "isScan", "minPixels", "dateTakenRange"}:
        return False
    if any(key in match and not isinstance(match[key], bool) for key in ("isScreenshot", "hasCamera", "isScan")):
        return False
    if "minPixels" in match and (type(match["minPixels"]) is not int or match["minPixels"] < 0):
        return False
    if "dateTakenRange" in match:
        value = match["dateTakenRange"]
        if not isinstance(value, list) or len(value) != 2 or not all(item is None or _iso_date(item) for item in value):
            return False
    return True


def rule_kind(rule: Dict[str, Any]) -> str:
    return rule.get("kind", "extension") if isinstance(rule, dict) else "extension"


def normalized_extension(value: str) -> str:
    return value.strip().lstrip(".").casefold()


def type_configuration(profile: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str, str]:
    params = profile.get("parameters", {})
    if "typeRules" in params:
        rules = params["typeRules"]
        unmatched = params.get("unmatchedAction", "other")
    else:
        enabled = params.get("categories", list(CATEGORIES))
        rules = [
            {
                "id": key,
                "name": category["label"],
                "folderName": category["label"],
                "extensions": category["extensions"],
                "enabled": key in enabled,
            }
            for key, category in CATEGORIES.items() if key != "other"
        ]
        unmatched = "other" if "other" in enabled else "keep"
    return rules, unmatched, params.get("otherFolder", "Other files")


def validate_type_configuration(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = profile.get("parameters", {})
    if "categories" in params and not isinstance(params["categories"], list):
        return [{"code": "INVALID_TYPE_RULES", "field": "parameters.categories"}]
    if "typeRules" in params and not isinstance(params["typeRules"], list):
        return [{"code": "INVALID_TYPE_RULES", "field": "parameters.typeRules"}]
    rules, unmatched, other_folder = type_configuration(profile)
    issues: List[Dict[str, Any]] = []
    ids = set()
    extensions = set()
    enabled_count = 0
    for index, rule in enumerate(rules):
        field = "parameters.typeRules.%d" % index
        if not isinstance(rule, dict):
            issues.append({"code": "INVALID_TYPE_RULES", "field": field})
            continue
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id or rule_id in ids:
            issues.append({"code": "INVALID_RULE_ID", "field": field})
        else:
            ids.add(rule_id)
        if not isinstance(rule.get("enabled"), bool):
            issues.append({"code": "INVALID_TYPE_RULES", "field": field})
            continue
        if not rule["enabled"]:
            continue
        enabled_count += 1
        name = rule.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            issues.append({"code": "INVALID_RULE_NAME", "field": field})
        if not valid_folder_name(rule.get("folderName")):
            issues.append({"code": "INVALID_RULE_FOLDER", "field": field})
        kind = rule_kind(rule)
        if kind not in RULE_KINDS:
            issues.append({"code": "INVALID_RULE_KIND", "field": field})
            continue
        description = rule.get("description")
        if description is not None and (not isinstance(description, str) or len(description) > 60):
            issues.append({"code": "INVALID_RULE_NAME", "field": field})
        if kind == "metadata" and not valid_match(rule.get("match")):
            issues.append({"code": "INVALID_RULE_MATCH", "field": field})
        if kind == "content" and (not isinstance(rule.get("centroidRef"), str) or not rule["centroidRef"]):
            issues.append({"code": "INVALID_RULE_MATCH", "field": field})
        values = rule.get("extensions", [] if kind == "content" else None)
        if not isinstance(values, list) or (not values and kind != "content"):
            issues.append({"code": "INVALID_RULE_EXTENSIONS", "field": field})
            continue
        for value in values:
            if not isinstance(value, str):
                issues.append({"code": "INVALID_RULE_EXTENSIONS", "field": field})
                continue
            extension = normalized_extension(value)
            if not re.fullmatch(r"[a-z0-9][a-z0-9_+\-]*", extension):
                issues.append({"code": "INVALID_RULE_EXTENSIONS", "field": field})
            elif kind != "extension":
                continue
            elif extension in extensions:
                issues.append({"code": "DUPLICATE_EXTENSION", "field": field, "extension": extension})
            else:
                extensions.add(extension)
    if unmatched not in {"keep", "other"}:
        issues.append({"code": "INVALID_UNMATCHED_ACTION", "field": "parameters.unmatchedAction"})
    elif unmatched == "other" and not valid_folder_name(other_folder):
        issues.append({"code": "INVALID_RULE_FOLDER", "field": "parameters.otherFolder"})
    if not enabled_count and unmatched != "other":
        issues.append({"code": "NO_CATEGORIES", "field": "parameters.typeRules"})
    return issues
