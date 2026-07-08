"""
PBIP Metadata Validation
========================
Static integrity checks for a Power BI Project (.pbip) folder, meant to run as a
CI gate BEFORE the BPA. Uses only the Python standard library (no pip install).

It produces:
  * Human-readable console output (for the Actions log).
  * A machine-readable results file (pbip_validation_results.json) consumed by
    pbip_pr_comment.py to post a comment on the pull request.
  * A GitHub Actions env var METADATA_VALIDATION_FAILED=true|false.

In GitHub Actions the script always exits 0 (a later workflow step fails the job
based on METADATA_VALIDATION_FAILED, so the PR comment can be posted first).
When run locally it exits 1 on failure so developers get immediate feedback.

Configure the project folder with the env var PBIP_PROJECT_DIR (default: pbi-project).
"""

import json
import os
import re
import subprocess
import sys

PROJECT_DIR = os.environ.get("PBIP_PROJECT_DIR", "pbi-project")
RESULTS_FILE = "pbip_validation_results.json"


def _resolve_project_roots():
    """Project roots to validate.

    PBIP_PROJECT_DIRS (space/comma/newline separated) takes precedence and is
    used by CI to validate ONLY the projects changed in a PR. Falls back to the
    single PBIP_PROJECT_DIR (default 'pbi-project') for local runs.
    An explicitly-set but empty PBIP_PROJECT_DIRS means 'no changed projects'.
    """
    raw = os.environ.get("PBIP_PROJECT_DIRS")
    if raw is not None:
        return [d for d in re.split(r"[\s,]+", raw.strip()) if d]
    return [PROJECT_DIR]


PROJECT_ROOTS = _resolve_project_roots()


def walk_projects():
    """os.walk over every selected project root."""
    for root_dir in PROJECT_ROOTS:
        for tup in os.walk(root_dir):
            yield tup

# Structured report: each entry describes one check.
REPORT = []

ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]|^\\\\|^file://|^/", re.IGNORECASE)


def add_result(title, what, why, status, details=None):
    """status: 'pass' | 'fail' | 'warn'."""
    REPORT.append({
        "title": title,
        "what": what,     # o que foi validado
        "why": why,       # por que a validacao importa
        "status": status,
        "details": details or [],
    })
    icon = {"pass": "[OK]", "fail": "[FAIL]", "warn": "[WARN]"}[status]
    print(f"\n{icon} {title}")
    print(f"     O que: {what}")
    print(f"     Porque: {why}")
    for d in (details or []):
        print(f"       - {d}")


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def rel(path):
    return os.path.relpath(path, ".").replace("\\", "/")


# ---------------------------------------------------------------------------
# Check 1: every *.json parses correctly
# ---------------------------------------------------------------------------
def check_json_well_formed():
    bad = []
    found = False
    for root, _dirs, files in walk_projects():
        for name in files:
            if name.lower().endswith(".json"):
                found = True
                p = os.path.join(root, name)
                try:
                    load_json(p)
                except Exception as e:  # noqa: BLE001
                    bad.append(f"{rel(p)} -> {e}")
    what = "Todos os arquivos *.json do projeto fazem parse (sintaxe valida)"
    why = "JSON malformado quebra a leitura do PBIP e impede o deploy no Fabric"
    if not found:
        add_result("JSON bem-formado", what, why, "warn",
                   ["Nenhum arquivo *.json encontrado"])
    elif bad:
        add_result("JSON bem-formado", what, why, "fail", bad)
    else:
        add_result("JSON bem-formado", what, why, "pass")


# ---------------------------------------------------------------------------
# Check 2 & 3: .pbip and .pbir references resolve
# ---------------------------------------------------------------------------
def check_pbip_references():
    details = []
    status = "pass"

    pbip_files = []
    for root, _dirs, files in walk_projects():
        for name in files:
            if name.lower().endswith(".pbip"):
                pbip_files.append(os.path.join(root, name))

    if not pbip_files:
        details.append("Nenhum arquivo .pbip encontrado")
        status = "fail"

    for pbip in pbip_files:
        base = os.path.dirname(pbip)
        try:
            data = load_json(pbip)
        except Exception as e:  # noqa: BLE001
            details.append(f"Nao foi possivel ler {rel(pbip)} -> {e}")
            status = "fail"
            continue
        for artifact in data.get("artifacts", []):
            for _kind, ref in artifact.items():
                path = ref.get("path", "")
                if ABSOLUTE_PATH_RE.match(path):
                    details.append(f"Caminho absoluto em {rel(pbip)}: '{path}'")
                    status = "fail"
                target = os.path.normpath(os.path.join(base, path))
                if not os.path.isdir(target):
                    details.append(f"{rel(pbip)} referencia pasta inexistente: '{path}'")
                    status = "fail"

    for root, _dirs, files in walk_projects():
        for name in files:
            if name.lower().endswith(".pbir"):
                p = os.path.join(root, name)
                try:
                    data = load_json(p)
                except Exception as e:  # noqa: BLE001
                    details.append(f"Nao foi possivel ler {rel(p)} -> {e}")
                    status = "fail"
                    continue
                by_path = (data.get("datasetReference", {}) or {}).get("byPath")
                if by_path:
                    path = by_path.get("path", "")
                    if ABSOLUTE_PATH_RE.match(path):
                        details.append(f"Caminho absoluto de dataset em {rel(p)}: '{path}'")
                        status = "fail"
                    target = os.path.normpath(os.path.join(os.path.dirname(p), path))
                    if not os.path.isdir(target):
                        details.append(f"{rel(p)} dataset byPath inexistente: '{path}'")
                        status = "fail"
                elif (data.get("datasetReference", {}) or {}).get("byConnection"):
                    details.append(f"{rel(p)} usa byConnection (modelo publicado, sem validacao local)")

    add_result(
        "Referencias do projeto",
        "O .pbip e o .pbir apontam para pastas .Report/.SemanticModel existentes, com caminhos relativos",
        "Referencia quebrada ou caminho absoluto impede abrir/portar o projeto em outra maquina",
        status, details,
    )


# ---------------------------------------------------------------------------
# Check 5 & 6 & 7: required files, version metadata, TMDL non-empty
# ---------------------------------------------------------------------------
def check_required_files():
    details = []
    status = "pass"
    for root, dirs, _files in walk_projects():
        for d in dirs:
            full = os.path.join(root, d)
            if d.endswith(".Report"):
                required = [
                    "definition.pbir",
                    os.path.join("definition", "report.json"),
                    os.path.join("definition", "version.json"),
                    os.path.join("definition", "pages", "pages.json"),
                    ".platform",
                ]
                for rq in required:
                    if not os.path.isfile(os.path.join(full, rq)):
                        details.append(f"Report '{d}' sem arquivo obrigatorio: {rq}")
                        status = "fail"
            if d.endswith(".SemanticModel"):
                required = [
                    "definition.pbism",
                    os.path.join("definition", "model.tmdl"),
                    os.path.join("definition", "database.tmdl"),
                    ".platform",
                ]
                for rq in required:
                    fp = os.path.join(full, rq)
                    if not os.path.isfile(fp):
                        details.append(f"SemanticModel '{d}' sem arquivo obrigatorio: {rq}")
                        status = "fail"
                    elif rq.endswith(".tmdl") and os.path.getsize(fp) == 0:
                        details.append(f"SemanticModel '{d}' com TMDL vazio: {rq}")
                        status = "fail"

    add_result(
        "Arquivos obrigatorios e TMDL",
        "Cada Report/SemanticModel tem seus arquivos-chave (.pbir/.pbism, report.json, version.json, pages.json, model/database.tmdl, .platform) e TMDL nao vazio",
        "A falta de um arquivo estrutural ou TMDL vazio corrompe o item e falha o deploy",
        status, details,
    )


# ---------------------------------------------------------------------------
# Check 8: registered report resources exist
# ---------------------------------------------------------------------------
def check_report_resources():
    details = []
    status = "pass"
    for root, _dirs, files in walk_projects():
        if os.path.basename(root) == "definition" and "report.json" in files:
            report_json = os.path.join(root, "report.json")
            report_folder = os.path.dirname(root)
            try:
                data = load_json(report_json)
            except Exception:  # noqa: BLE001
                continue
            for pkg in data.get("resourcePackages", []):
                pkg_name = pkg.get("name", "RegisteredResources")
                for item in pkg.get("items", []):
                    item_path = item.get("path", "")
                    resource_fp = os.path.join(
                        report_folder, "StaticResources", pkg_name, item_path
                    )
                    if not os.path.isfile(resource_fp):
                        details.append(f"Recurso referenciado mas ausente: {pkg_name}/{item_path}")
                        status = "fail"

    add_result(
        "Recursos registrados existem",
        "Imagens e temas listados em resourcePackages apontam para arquivos reais em StaticResources",
        "Uma referencia quebrada de imagem/tema gera erro visual ou de carregamento no relatorio",
        status, details,
    )


# ---------------------------------------------------------------------------
# Check 9: .gitignore hygiene
# ---------------------------------------------------------------------------
def check_gitignore_hygiene():
    details = []
    status = "pass"

    gitignores = [g for g in dict.fromkeys(
                      [".gitignore"] + [os.path.join(r, ".gitignore") for r in PROJECT_ROOTS])
                  if os.path.isfile(g)]
    contents = ""
    for gi in gitignores:
        with open(gi, "r", encoding="utf-8-sig") as f:
            contents += f.read() + "\n"

    if not gitignores:
        details.append("Nenhum .gitignore encontrado - cache/credenciais locais podem vazar")
        status = "warn"
    else:
        for needle in ("localSettings.json", "cache.abf"):
            if needle not in contents:
                details.append(f".gitignore nao menciona '{needle}'")
                if status == "pass":
                    status = "warn"

    try:
        tracked = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        committed_bad = [f for f in tracked
                         if f.endswith("localSettings.json") or f.endswith(".abf")]
        for f in committed_bad:
            details.append(f"Artefato local commitado indevidamente: {f}")
            status = "fail"
    except (subprocess.CalledProcessError, FileNotFoundError):
        details.append("git indisponivel - checagem de artefatos rastreados pulada")
        if status == "pass":
            status = "warn"

    add_result(
        "Higiene do .gitignore",
        "Arquivos locais (localSettings.json, cache.abf) estao ignorados e NAO foram commitados",
        "Cache e credenciais locais nao devem ser versionados (poluicao e risco de seguranca)",
        status, details,
    )


def _finish(failed):
    counts = {
        "pass": sum(1 for r in REPORT if r["status"] == "pass"),
        "warn": sum(1 for r in REPORT if r["status"] == "warn"),
        "fail": sum(1 for r in REPORT if r["status"] == "fail"),
    }
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump({"failed": failed, "counts": counts, "checks": REPORT}, f,
                  ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"Resumo: {counts['pass']} ok, {counts['warn']} avisos, {counts['fail']} falhas")

    # Signal the result to the workflow (a later step fails the job).
    gh_env = os.environ.get("GITHUB_ENV")
    if gh_env:
        with open(gh_env, "a", encoding="utf-8") as env_file:
            env_file.write(f"METADATA_VALIDATION_FAILED={'true' if failed else 'false'}\n")

    print("PBIP metadata validation " + ("FAILED." if failed else "PASSED."))

    # In CI, exit 0 so the comment step can run; the fail step handles the gate.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        sys.exit(0)
    sys.exit(1 if failed else 0)


def main():
    if not PROJECT_ROOTS:
        print("PBIP Metadata Validation - nenhum projeto PBIP alterado; nada a validar.")
        REPORT.append({
            "title": "Projetos alterados",
            "what": "Nenhum projeto PBIP foi alterado neste PR",
            "why": "Sem alteracoes em projetos PBIP nao ha o que validar nesta etapa",
            "status": "pass",
            "details": [],
        })
        _finish(failed=False)
        return

    print(f"PBIP Metadata Validation - projetos: {', '.join(PROJECT_ROOTS)}")
    missing = [r for r in PROJECT_ROOTS if not os.path.isdir(r)]
    if missing:
        print(f"::error::Project folder(s) not found: {', '.join(missing)}")
        REPORT.append({
            "title": "Pasta do projeto",
            "what": "As pastas de projeto informadas existem",
            "why": "Sem a pasta do projeto nao ha o que validar",
            "status": "fail",
            "details": [f"Pasta nao encontrada: {m}" for m in missing],
        })
        _finish(failed=True)
        return

    check_json_well_formed()
    check_pbip_references()
    check_required_files()
    check_report_resources()
    check_gitignore_hygiene()

    failed = any(r["status"] == "fail" for r in REPORT)
    _finish(failed)


if __name__ == "__main__":
    main()
