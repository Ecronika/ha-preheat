import os
import json
import re
import ast

def get_placeholders_from_string(s: str) -> set[str]:
    return set(re.findall(r"\{([a-zA-Z0-9_]+)\}", s))

def extract_placeholders_from_json(json_data):
    issues = {}
    issues_section = json_data.get("issues", {})
    for issue_key, issue_val in issues_section.items():
        placeholders = set()
        if "title" in issue_val:
            placeholders.update(get_placeholders_from_string(issue_val["title"]))
        if "description" in issue_val:
            placeholders.update(get_placeholders_from_string(issue_val["description"]))
        issues[issue_key] = placeholders
    return issues

def find_issues_in_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filepath)
        
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
                
            if func_name in ("_create_issue", "async_create_issue"):
                issue_id = None
                if func_name == "_create_issue" and len(node.args) >= 1:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant):
                        issue_id = first_arg.value
                    elif isinstance(first_arg, ast.Str):
                        issue_id = first_arg.s
                
                kwargs = {kw.arg: kw.value for kw in node.keywords}
                
                translation_key = issue_id
                if "translation_key" in kwargs:
                    key_val = kwargs["translation_key"]
                    if isinstance(key_val, ast.Constant):
                        translation_key = key_val.value
                    elif isinstance(key_val, ast.Str):
                        translation_key = key_val.s
                
                placeholders = set()
                if func_name == "_create_issue":
                    placeholders.add("name")
                    
                if "translation_placeholders" in kwargs:
                    ph_val = kwargs["translation_placeholders"]
                    if isinstance(ph_val, ast.Dict):
                        for k in ph_val.keys:
                            if isinstance(k, ast.Constant):
                                placeholders.add(k.value)
                            elif isinstance(k, ast.Str):
                                placeholders.add(k.s)
                                
                if translation_key:
                    issues.append((translation_key, placeholders))
    return issues

def test_json_placeholders_consistency():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    strings_path = os.path.join(base_dir, "custom_components", "preheat", "strings.json")
    en_path = os.path.join(base_dir, "custom_components", "preheat", "translations", "en.json")
    de_path = os.path.join(base_dir, "custom_components", "preheat", "translations", "de.json")
    
    with open(strings_path, "r", encoding="utf-8") as f:
        strings_json = json.load(f)
    with open(en_path, "r", encoding="utf-8") as f:
        en_json = json.load(f)
    with open(de_path, "r", encoding="utf-8") as f:
        de_json = json.load(f)
        
    strings_issues = extract_placeholders_from_json(strings_json)
    en_issues = extract_placeholders_from_json(en_json)
    de_issues = extract_placeholders_from_json(de_json)
    
    all_keys = set(strings_issues.keys()) | set(en_issues.keys()) | set(de_issues.keys())
    
    # 1. Assert all files define the same issue keys
    assert strings_issues.keys() == en_issues.keys(), f"Mismatched keys: strings.json vs en.json: {strings_issues.keys() ^ en_issues.keys()}"
    assert strings_issues.keys() == de_issues.keys(), f"Mismatched keys: strings.json vs de.json: {strings_issues.keys() ^ de_issues.keys()}"
    
    # 2. Assert all files define the exact same set of placeholders for each issue
    for key in all_keys:
        ph_strings = strings_issues[key]
        ph_en = en_issues[key]
        ph_de = de_issues[key]
        assert ph_strings == ph_en, f"Placeholder mismatch for '{key}': strings.json ({ph_strings}) vs en.json ({ph_en})"
        assert ph_strings == ph_de, f"Placeholder mismatch for '{key}': strings.json ({ph_strings}) vs de.json ({ph_de})"

def test_code_placeholders_superset():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    strings_path = os.path.join(base_dir, "custom_components", "preheat", "strings.json")
    
    with open(strings_path, "r", encoding="utf-8") as f:
        strings_json = json.load(f)
    strings_issues = extract_placeholders_from_json(strings_json)
    
    diag_path = os.path.join(base_dir, "custom_components", "preheat", "diagnostics.py")
    coord_path = os.path.join(base_dir, "custom_components", "preheat", "coordinator.py")
    
    code_issues = find_issues_in_file(diag_path) + find_issues_in_file(coord_path)
    
    for key, code_ph in code_issues:
        # Check if the key exists in translation files
        assert key in strings_issues, f"Issue key '{key}' raised in code is missing from translation files"
        
        json_ph = strings_issues[key]
        
        # Code placeholders must be a superset of translation placeholders (code_ph >= json_ph)
        assert json_ph.issubset(code_ph), f"Missing placeholders in code call for key '{key}': Code supplies {code_ph}, but translations use {json_ph}. Missing: {json_ph - code_ph}"
