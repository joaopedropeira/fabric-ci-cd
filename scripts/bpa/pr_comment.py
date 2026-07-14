
import pandas as pd
import requests
import os
import json
import re

# --- Configuration ---
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
REPO = os.getenv('REPO')
RUN_ID = os.getenv('GITHUB_RUN_ID')
PR_NUMBER = os.getenv('PR_NUMBER')

# --- Load CSVs ---
must_correct = pd.read_csv('must_correct.csv')
correct_asap = pd.read_csv('correct_asap.csv')
nice_to_have = pd.read_csv('nice_to_have.csv')

# --- Load Rules with anchors ---
with open("scripts/bpa/BPA_Rules.json") as f:
    RULES = {r['Name']: r for r in json.load(f)}

# --- Helpers ---
def get_anchor(rule_name):
    anchor = RULES.get(rule_name, {}).get("Anchor", "")
    if not anchor:
        anchor = re.sub(r'[^a-zA-Z0-9]+', '-', rule_name.strip()).lower()
    return anchor


def format_violations(df, expanded=True):
    if df.empty:
        return ""

    output = []
    grouped = df.groupby('RuleName')
    for rule, group in grouped:
        objects = group[['ObjectName', 'ObjectType']].dropna().drop_duplicates().values.tolist()
        anchor = get_anchor(rule)
        rule_link = f"https://github.com/joaopedropeira/fabric-ci-cd/blob/main/scripts/bpa/bpa_rules.md#{anchor}"

        output.append(
            f"<details{' open' if expanded else ''}>\n"
            f"<summary><h4>🔎 {rule} – "
            f"<a href='{rule_link}' target='_blank'>Descrição da regra 🔗</a></h4></summary>\n"
        )

        formatted_objects = [f"**{obj}** ({typ})" for obj, typ in objects]
        if len(formatted_objects) > 10:
            columns = [formatted_objects[i::3] for i in range(3)]
            max_len = max(len(col) for col in columns)
            output.append("\n| Lista de ocorrências | Lista de ocorrências | Lista de ocorrências |")
            output.append("|:---------------------|:---------------------|:---------------------|")
            for i in range(max_len):
                row = [columns[col][i] if i < len(columns[col]) else "" for col in range(3)]
                output.append("| " + " | ".join(row) + " |")
        else:
            output.extend([f"- {item}" for item in formatted_objects])

        output.append("</details>\n\n\n")
    return "\n".join(output)


def build_rule_summary(df):
    if df.empty:
        return ""
    rule_counts = df['RuleName'].value_counts().reset_index()
    rule_counts.columns = ['RuleName', 'Violations']
    rule_counts = rule_counts.sort_values('Violations', ascending=False)
    table = "| Regra | Ocorrências |\n|:------|-----------:|\n"
    table += "\n".join([f"| {row['RuleName']} | {row['Violations']} |" for _, row in rule_counts.iterrows()])
    return table

def generate_message(include_sev3=True, include_sev2=True, include_sev1=True, summary_only_sev1=False, summary_only_sev2=False):
    message = result_message + artifact_section + summary_table
    if include_sev3:
        message += f"\n\n## 🚨 Corrigir obrigatoriamente (Severidade 3)\n\n{build_rule_summary(must_correct)}\n\n{format_violations(must_correct)}"
    if include_sev2:
        message += "\n\n## ⚡ Corrigir o quanto antes (Severidade 2)\n\n"
        message += build_rule_summary(correct_asap)
        if not summary_only_sev2:
            message += f"\n\n{format_violations(correct_asap)}"
        else:
            message += "\n\nProblemas demais para exibir. Consulte os artefatos para o resultado completo.\n"
    if include_sev1:
        message += "\n\n## 💡 Bom ter (Severidade 1)\n\n"
        message += build_rule_summary(nice_to_have)
        if not summary_only_sev1:
            message += f"\n\n<details><summary><strong>Clique para ver os detalhes</strong></summary>\n\n{format_violations(nice_to_have)}\n</details>"
        else:
            message += "\n\nProblemas demais para exibir. Consulte os artefatos para o resultado completo.\n"
    return message

# --- Result Status ---
if must_correct.empty:
    if correct_asap.empty:
        result_message = (
            "# ✅ O modelo pode ser publicado. Nenhum problema de Severidade 3 (crítica) ou Severidade 2 encontrado.\n\n"
            "### 💡 Você ainda pode melhorar a qualidade do modelo tratando os problemas de Severidade 1 (se houver)."
        )
    else:
        result_message = (
            "# ✅ O modelo pode ser publicado. Nenhum problema de Severidade 3 (crítica) encontrado.\n\n"
            "### ⚡ Ainda assim, corrija os problemas de Severidade 2 o quanto antes para melhorar a qualidade do modelo!"
        )
else:
    result_message = "# ❌ O modelo não pode ser publicado enquanto os problemas de Severidade 3 não forem corrigidos."

artifact_link = f"https://github.com/{REPO}/actions/runs/{RUN_ID}"
artifact_section = f"\n\n📂 **Resultado do BPA e análise (downloads em CSV):** [Ver arquivos .zip aqui]({artifact_link})\n"

summary_table = f"""### 📊 Resumo

| Nível de Severidade | Nº de Problemas |
|:--------------------|----------------:|
| 🚨 Corrigir obrigatoriamente | {len(must_correct)} |
| ⚡ Corrigir o quanto antes | {len(correct_asap)} |
| 💡 Bom ter | {len(nice_to_have)} |
"""

# --- Generate the PR body with fallback truncation ---
comment_body = generate_message()
if len(comment_body) > 65000:
    comment_body = generate_message(include_sev3=True, include_sev2=True, include_sev1=True, summary_only_sev1=True)
if len(comment_body) > 65000:
    comment_body = generate_message(include_sev3=True, include_sev2=True, summary_only_sev2=True, include_sev1=False)
if len(comment_body) > 65000:
    comment_body = generate_message(include_sev3=True, include_sev2=False, include_sev1=False)
if len(comment_body) > 65000:
    comment_body = generate_message(include_sev3=False, include_sev2=False, include_sev1=True)

# --- Post PR Comment ---
url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
payload = {"body": comment_body}
headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}
response = requests.post(url, headers=headers, data=json.dumps(payload))
if response.status_code != 201:
    print(f"Failed to comment on PR: {response.status_code} - {response.text}")
else:
    print("Successfully added comment to PR.")

# --- Label PR ---
if not must_correct.empty:
    new_label = "bpa-failed"
elif not correct_asap.empty:
    new_label = "bpa-warning"
else:
    new_label = "bpa-passed"

labels_url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/labels"
labels_response = requests.get(labels_url, headers=headers)

if labels_response.status_code == 200:
    existing_labels = [label['name'] for label in labels_response.json()]
    old_bpa_labels = [label for label in existing_labels if label.startswith("bpa-")]

    for label in old_bpa_labels:
        delete_url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/labels/{label}"
        delete_response = requests.delete(delete_url, headers=headers)
        if delete_response.status_code == 200:
            print(f"Removed old label: {label}")
        else:
            print(f"Failed to remove label: {label} | {delete_response.text}")
else:
    print(f"Failed to fetch existing labels: {labels_response.text}")

add_payload = {"labels": [new_label]}
add_response = requests.post(labels_url, headers=headers, data=json.dumps(add_payload))
if add_response.status_code in (200, 201):
    print(f"Successfully applied label: {new_label}")
else:
    print(f"Failed to apply label: {add_response.status_code} - {add_response.text}")
