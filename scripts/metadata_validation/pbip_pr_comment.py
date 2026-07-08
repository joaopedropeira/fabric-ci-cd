"""
PBIP Metadata Validation - Pull Request comment
===============================================
Reads pbip_validation_results.json (produced by pbip_metadata_validation.py) and
posts a structured comment on the pull request, plus a status label
(metadata-passed / metadata-failed). Mirrors the BPA pr_comment.py pattern.

Env vars (provided by the workflow):
  GITHUB_TOKEN, REPO (owner/name), PR_NUMBER, GITHUB_RUN_ID
"""

import json
import os

import requests

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("REPO")
RUN_ID = os.getenv("GITHUB_RUN_ID")
PR_NUMBER = os.getenv("PR_NUMBER")
RESULTS_FILE = "pbip_validation_results.json"

STATUS_ICON = {"pass": "✅", "fail": "❌", "warn": "⚠️"}
STATUS_TEXT = {"pass": "Passou", "fail": "Falhou", "warn": "Aviso"}

with open(RESULTS_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

failed = data["failed"]
counts = data["counts"]
checks = data["checks"]

# ---- Header -------------------------------------------------------------
if failed:
    header = "# ❌ Validação de metadados PBIP falhou\n\nCorrija os itens abaixo antes de prosseguir. O BPA não roda enquanto esta etapa falhar."
else:
    header = "# ✅ Validação de metadados PBIP passou\n\nA integridade e a sintaxe dos arquivos do projeto estão OK. O BPA prossegue."

artifact_link = f"https://github.com/{REPO}/actions/runs/{RUN_ID}"

summary = (
    "\n\n### 📊 Resumo\n\n"
    "| Status | Quantidade |\n"
    "|:-------|-----------:|\n"
    f"| ✅ Passou | {counts['pass']} |\n"
    f"| ⚠️ Aviso | {counts['warn']} |\n"
    f"| ❌ Falhou | {counts['fail']} |\n"
    f"\n📂 **Log completo:** [Ver execução aqui]({artifact_link})\n"
)

# ---- Detail table -------------------------------------------------------
table = (
    "\n### 🔍 Verificações\n\n"
    "| Resultado | Verificação | O que foi validado | Por que importa |\n"
    "|:---------:|:------------|:-------------------|:----------------|\n"
)
for c in checks:
    icon = STATUS_ICON.get(c["status"], "")
    table += (
        f"| {icon} {STATUS_TEXT.get(c['status'], '')} "
        f"| **{c['title']}** "
        f"| {c['what']} "
        f"| {c['why']} |\n"
    )

# ---- Details for non-pass checks ---------------------------------------
details_md = ""
problem_checks = [c for c in checks if c["status"] != "pass" and c["details"]]
if problem_checks:
    details_md += "\n### 🧾 Detalhes\n"
    for c in problem_checks:
        icon = STATUS_ICON.get(c["status"], "")
        details_md += f"\n<details open>\n<summary>{icon} <strong>{c['title']}</strong></summary>\n\n"
        for d in c["details"]:
            details_md += f"- {d}\n"
        details_md += "\n</details>\n"

comment_body = header + summary + table + details_md

# ---- Post comment -------------------------------------------------------
headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
resp = requests.post(url, headers=headers, data=json.dumps({"body": comment_body}))
if resp.status_code != 201:
    print(f"Failed to comment on PR: {resp.status_code} - {resp.text}")
else:
    print("Successfully added metadata validation comment to PR.")

# ---- Label PR -----------------------------------------------------------
new_label = "metadata-failed" if failed else "metadata-passed"
labels_url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/labels"
labels_resp = requests.get(labels_url, headers=headers)
if labels_resp.status_code == 200:
    existing = [lbl["name"] for lbl in labels_resp.json()]
    for lbl in [x for x in existing if x.startswith("metadata-")]:
        del_url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/labels/{lbl}"
        requests.delete(del_url, headers=headers)

add_resp = requests.post(labels_url, headers=headers, data=json.dumps({"labels": [new_label]}))
if add_resp.status_code in (200, 201):
    print(f"Applied label: {new_label}")
else:
    print(f"Failed to apply label: {add_resp.status_code} - {add_resp.text}")
