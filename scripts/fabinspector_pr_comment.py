"""
Fab Inspector (report rules) - Pull Request comment
==================================================
Reads the captured Fab Inspector console output (fabinspector_console.txt) and the
REPORT_RULES_FAILED env var, then posts a comment on the pull request and applies a
status label (reportrules-passed / reportrules-failed). Mirrors the BPA / metadata
comment pattern so each gate reports its own results.

Env vars (provided by the workflow):
  GITHUB_TOKEN, REPO (owner/name), PR_NUMBER, GITHUB_RUN_ID, REPORT_RULES_FAILED
"""

import json
import os

import requests

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("REPO")
RUN_ID = os.getenv("GITHUB_RUN_ID")
PR_NUMBER = os.getenv("PR_NUMBER")
FAILED = os.getenv("REPORT_RULES_FAILED", "false").lower() == "true"
CONSOLE_FILE = "fabinspector_console.txt"

console = ""
if os.path.isfile(CONSOLE_FILE):
    with open(CONSOLE_FILE, "r", encoding="utf-8", errors="replace") as f:
        console = f.read().strip()

# GitHub comment hard limit is ~65k chars; keep a safe margin for the console block.
MAX_CONSOLE = 55000
truncated = False
if len(console) > MAX_CONSOLE:
    console = console[-MAX_CONSOLE:]
    truncated = True

if FAILED:
    header = (
        "# ❌ Regras de relatório (PBI Inspector) falharam\n\n"
        "O Fab Inspector encontrou violações de boas práticas no relatório. "
        "Veja os detalhes abaixo (e as anotações inline na aba *Files changed*)."
    )
else:
    header = (
        "# ✅ Regras de relatório (PBI Inspector) passaram\n\n"
        "O relatório está de acordo com as regras de boas práticas visuais (VisOps)."
    )

artifact_link = f"https://github.com/{REPO}/actions/runs/{RUN_ID}"
intro = (
    f"\n\n📂 **Log completo e artefatos:** [Ver execução aqui]({artifact_link})\n"
    "\n> As regras validam a **camada visual** do relatório (nº de visuais por página, "
    "cores fora do tema, páginas ocultas, etc.) — complementar ao BPA, que valida o modelo.\n"
)

if console:
    note = "\n\n_(saída truncada — veja o log completo da execução)_" if truncated else ""
    details = (
        "\n<details open>\n<summary><strong>🔍 Resultado do Fab Inspector</strong></summary>\n\n"
        f"```\n{console}\n```{note}\n</details>\n"
    )
else:
    details = "\n_(sem saída de console capturada)_\n"

comment_body = header + intro + details

headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
resp = requests.post(url, headers=headers, data=json.dumps({"body": comment_body}))
if resp.status_code != 201:
    print(f"Failed to comment on PR: {resp.status_code} - {resp.text}")
else:
    print("Successfully added report rules comment to PR.")

# ---- Label PR -----------------------------------------------------------
new_label = "reportrules-failed" if FAILED else "reportrules-passed"
labels_url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/labels"
labels_resp = requests.get(labels_url, headers=headers)
if labels_resp.status_code == 200:
    existing = [lbl["name"] for lbl in labels_resp.json()]
    for lbl in [x for x in existing if x.startswith("reportrules-")]:
        del_url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/labels/{lbl}"
        requests.delete(del_url, headers=headers)

add_resp = requests.post(labels_url, headers=headers, data=json.dumps({"labels": [new_label]}))
if add_resp.status_code in (200, 201):
    print(f"Applied label: {new_label}")
else:
    print(f"Failed to apply label: {add_resp.status_code} - {add_resp.text}")
