from flask import Flask, render_template, jsonify, request
import json
import os
import subprocess
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
app = Flask(__name__)

def carregar_mencoes():
    if os.path.exists("mencoes.json"):
        with open("mencoes.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def salvar_mencoes(mencoes):
    with open("mencoes.json", "w", encoding="utf-8") as f:
        json.dump(mencoes, f, ensure_ascii=False, indent=2)

def carregar_feedbacks():
    if os.path.exists("feedbacks.json"):
        with open("feedbacks.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def salvar_feedbacks(feedbacks):
    with open("feedbacks.json", "w", encoding="utf-8") as f:
        json.dump(feedbacks, f, ensure_ascii=False, indent=2)

def carregar_termos():
    if os.path.exists("termos.json"):
        with open("termos.json", "r", encoding="utf-8") as f:
            return json.load(f)
    termos_padrao = ["Daikin+Brasil"]
    salvar_termos(termos_padrao)
    return termos_padrao

def salvar_termos(termos):
    with open("termos.json", "w", encoding="utf-8") as f:
        json.dump(termos, f, ensure_ascii=False, indent=2)

def garantir_daikin(termo):
    palavras = termo.lower().split()
    if "daikin" not in palavras:
        return "Daikin " + termo
    return termo

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/mencoes")
def api_mencoes():
    return jsonify(carregar_mencoes())

@app.route("/api/stats")
def api_stats():
    mencoes = carregar_mencoes()
    stats = {
        "total": len(mencoes),
        "positivo": sum(1 for m in mencoes if m.get("sentimento") == "POSITIVO"),
        "negativo": sum(1 for m in mencoes if m.get("sentimento") == "NEGATIVO"),
        "oportunidade": sum(1 for m in mencoes if m.get("sentimento") == "OPORTUNIDADE"),
        "neutro": sum(1 for m in mencoes if m.get("sentimento") == "NEUTRO"),
        "informativo": sum(1 for m in mencoes if m.get("sentimento") == "INFORMATIVO"),
        "ultima_atualizacao": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    return jsonify(stats)

@app.route("/api/termos", methods=["GET"])
def api_termos_get():
    return jsonify(carregar_termos())

@app.route("/api/termos", methods=["POST"])
def api_termos_post():
    dados = request.json
    termos = dados.get("termos", [])
    termos_formatados = []
    for t in termos:
        t = t.strip()
        if not t:
            continue
        t = garantir_daikin(t)
        termos_formatados.append(t.replace(" ", "+"))
    if not termos_formatados:
        termos_formatados = ["Daikin+Brasil"]
    salvar_termos(termos_formatados)
    return jsonify({"ok": True, "termos": termos_formatados})

@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    dados = request.json
    link = dados.get("link")
    classificacao_correta = dados.get("classificacao_correta")
    motivo = dados.get("motivo", "")

    mencoes = carregar_mencoes()
    titulo_mencao = ""
    for m in mencoes:
        if m["link"] == link:
            m["sentimento_original"] = m["sentimento"]
            m["sentimento"] = classificacao_correta
            m["feedback"] = motivo
            titulo_mencao = m["titulo"]
            break
    salvar_mencoes(mencoes)

    feedbacks = carregar_feedbacks()
    feedbacks.append({
        "titulo": titulo_mencao,
        "link": link,
        "classificacao_original": dados.get("classificacao_original"),
        "classificacao_correta": classificacao_correta,
        "motivo": motivo,
        "data": datetime.now().strftime("%d/%m/%Y %H:%M")
    })
    salvar_feedbacks(feedbacks)
    return jsonify({"ok": True})

@app.route("/api/varrer", methods=["POST"])
def api_varrer():
    subprocess.Popen(["py", "monitor.py"])
    return jsonify({"ok": True, "mensagem": "Varredura iniciada!"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)