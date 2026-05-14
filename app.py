from flask import Flask, render_template, jsonify, request
import json
import os
import threading
import feedparser
import requests
import anthropic
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

CHAVE_API = os.getenv("ANTHROPIC_API_KEY")
CHAVE_YOUTUBE = os.getenv("YOUTUBE_API_KEY")
EMAIL_ENVIO = os.getenv("EMAIL_ENVIO")
EMAIL_SENHA = os.getenv("EMAIL_SENHA")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")

ARQUIVO_HISTORICO = "historico.json"
ARQUIVO_MENCOES = "mencoes.json"
ARQUIVO_TERMOS = "termos.json"
ARQUIVO_FEEDBACKS = "feedbacks.json"

BLOGS_RSS = [
    "https://www.webarcondicionado.com.br/feed",
    "https://blogdofrio.com.br/feed",
    "https://blogclimatiza.com.br/feed",
    "https://revistadofrio.com.br/feed",
    "https://infohvac.com.br/feed",
]

varrendo = False

def carregar_json(arquivo, padrao):
    if os.path.exists(arquivo):
        with open(arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    return padrao

def salvar_json(arquivo, dados):
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

def carregar_termos():
    termos = carregar_json(ARQUIVO_TERMOS, ["Daikin+Brasil"])
    if not termos:
        termos = ["Daikin+Brasil"]
    return termos

def ja_visto(link, historico):
    return any(h.get("link") == link for h in historico)

def carregar_exemplos_feedback():
    feedbacks = carregar_json(ARQUIVO_FEEDBACKS, [])
    if not feedbacks:
        return ""
    exemplos = "\n\nExemplos de correções feitas pela equipe Daikin:\n"
    for fb in feedbacks[-10:]:
        exemplos += f'- Título: "{fb["titulo"]}" → Correto: {fb["classificacao_correta"]}'
        if fb.get("motivo"):
            exemplos += f' (motivo: {fb["motivo"]})'
        exemplos += "\n"
    return exemplos

def extrair_conteudo(url):
    try:
        from newspaper import Article
        artigo = Article(url, language="pt")
        artigo.download()
        artigo.parse()
        texto = artigo.text[:2000]
        return texto if texto else ""
    except:
        return ""

def analisar_sentimento(titulo, conteudo=""):
    try:
        cliente = anthropic.Anthropic(api_key=CHAVE_API)
        texto_analise = f"Título: {titulo}"
        if conteudo:
            texto_analise += f"\n\nConteúdo: {conteudo[:1500]}"
        exemplos = carregar_exemplos_feedback()
        resposta = cliente.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": f"""Você é um analista de reputação da marca Daikin no Brasil, fabricante de ar condicionado.

Analise o título e conteúdo abaixo e responda em duas palavras separadas por vírgula:
1. Este conteúdo menciona diretamente a marca Daikin? (SIM ou NAO)
2. Qual a categoria?

Categorias:
- NEGATIVO: reclamações, defeitos, problemas, queda de desempenho, barulho, assistência ruim, preço abusivo
- POSITIVO: elogios, premiações, crescimento, lançamentos, parcerias, eficiência, economia de energia
- OPORTUNIDADE: dúvidas técnicas, perguntas sobre instalação, manutenção, comparações entre marcas, pedido de indicação
- NEUTRO: notícias factuais sem julgamento de valor
- INFORMATIVO: cita Daikin de forma indireta ou superficial
{exemplos}
Exemplo de resposta: SIM,NEGATIVO

{texto_analise}"""
            }]
        )
        resultado = resposta.content[0].text.strip().upper()
        if "NAO" in resultado or "NÃO" in resultado:
            return "INFORMATIVO"
        if "NEGATIVO" in resultado:
            return "NEGATIVO"
        if "POSITIVO" in resultado:
            return "POSITIVO"
        if "OPORTUNIDADE" in resultado:
            return "OPORTUNIDADE"
        if "INFORMATIVO" in resultado:
            return "INFORMATIVO"
        return "NEUTRO"
    except:
        return "NEUTRO"

def buscar_youtube(termo):
    try:
        url = "https://www.googleapis.com/youtube/v3/search"
        termo_limpo = termo.replace("+", " ")
        params = {
            "part": "snippet",
            "q": termo_limpo,
            "type": "video",
            "order": "date",
            "maxResults": 10,
            "regionCode": "BR",
            "relevanceLanguage": "pt",
            "key": CHAVE_YOUTUBE
        }
        resposta = requests.get(url, params=params)
        dados = resposta.json()
        mencoes = []
        palavras_portugues = ["ção", "ões", "ão", "condicionado", "instalação", "climatização",
                              "assistência", "manutenção", "inverter", "split", "preço", "comprar",
                              "brasil", "brasileiro", "avaliação", "como", "para", "com", "não",
                              "está", "uma", "que", "daikin"]
        for item in dados.get("items", []):
            titulo = item["snippet"]["title"]
            descricao = item["snippet"].get("description", "")
            canal = item["snippet"].get("channelTitle", "")
            texto_completo = (titulo + " " + descricao + " " + canal).lower()
            if "daikin" not in texto_completo:
                continue
            tem_portugues = any(p in texto_completo for p in palavras_portugues)
            if not tem_portugues:
                continue
            mencoes.append({
                "titulo": titulo,
                "conteudo": descricao,
                "link": f"https://youtube.com/watch?v={item['id']['videoId']}",
                "fonte": "YouTube",
                "termo": termo_limpo,
                "data": datetime.now().strftime("%d/%m/%Y %H:%M")
            })
        return mencoes
    except:
        return []

def enviar_email(novas_mencoes):
    try:
        positivas = [m for m in novas_mencoes if m["sentimento"] == "POSITIVO"]
        negativas = [m for m in novas_mencoes if m["sentimento"] == "NEGATIVO"]
        neutras = [m for m in novas_mencoes if m["sentimento"] == "NEUTRO"]
        oportunidades = [m for m in novas_mencoes if m["sentimento"] == "OPORTUNIDADE"]
        informativas = [m for m in novas_mencoes if m["sentimento"] == "INFORMATIVO"]

        msg = MIMEMultipart()
        msg["From"] = EMAIL_ENVIO
        msg["To"] = EMAIL_DESTINO
        msg["Subject"] = f"📊 Monitor Daikin — {len(novas_mencoes)} nova(s) menção(ões)"

        corpo = f"""
        <h2>📊 Resumo de Novas Menções — Daikin Brasil</h2>
        <p>Encontramos <strong>{len(novas_mencoes)}</strong> nova(s) menção(ões).</p>
        <table style="width:100%; border-collapse:collapse; margin:16px 0">
            <tr>
                <td style="padding:10px; background:#ffebee; text-align:center">😟<br><strong>{len(negativas)}</strong><br>Negativas</td>
                <td style="padding:10px; background:#fff3e0; text-align:center">💡<br><strong>{len(oportunidades)}</strong><br>Oportunidades</td>
                <td style="padding:10px; background:#e8f5e9; text-align:center">😊<br><strong>{len(positivas)}</strong><br>Positivas</td>
                <td style="padding:10px; background:#f5f5f5; text-align:center">😐<br><strong>{len(neutras)}</strong><br>Neutras</td>
                <td style="padding:10px; background:#e3f2fd; text-align:center">📰<br><strong>{len(informativas)}</strong><br>Informativas</td>
            </tr>
        </table>
        """

        def bloco(titulo_secao, lista, cor):
            if not lista:
                return ""
            html = f"<h3 style='color:{cor}'>{titulo_secao}</h3>"
            for m in lista:
                html += f"""
                <div style="border-left:4px solid {cor}; padding:8px 12px; margin:8px 0; background:#fafafa">
                    <p><strong>{m['titulo']}</strong></p>
                    <p>📍 {m['fonte']} | 📅 {m['data']}</p>
                    <p>🔗 <a href="{m['link']}">{m['link'][:80]}</a></p>
                </div>"""
            return html

        corpo += bloco("😟 Negativas", negativas, "#e53935")
        corpo += bloco("💡 Oportunidades", oportunidades, "#f57c00")
        corpo += bloco("😊 Positivas", positivas, "#43a047")
        corpo += bloco("😐 Neutras", neutras, "#757575")
        corpo += bloco("📰 Informativas", informativas, "#1565c0")
        corpo += "<hr><p><small>Monitor automático Daikin Brasil</small></p>"

        msg.attach(MIMEText(corpo, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as servidor:
            servidor.login(EMAIL_ENVIO, EMAIL_SENHA)
            servidor.sendmail(EMAIL_ENVIO, EMAIL_DESTINO, msg.as_string())
    except Exception as e:
        print(f"Erro ao enviar email: {e}")

def executar_varredura():
    global varrendo
    varrendo = True
    try:
        termos = carregar_termos()
        historico = carregar_json(ARQUIVO_HISTORICO, [])
        links_ocultos = [h["link"] for h in historico if h.get("oculto")]
        todas = []

        for termo in termos:
            termo_display = termo.replace("+", " ")
            fontes_rss = [
                f"https://news.google.com/rss/search?q={termo}&hl=pt-BR&gl=BR&ceid=BR:pt-419",
                f"https://www.reddit.com/r/brasil/search.rss?q={termo}&sort=new&restrict_sr=1",
                f"https://www.reddit.com/r/arCondicionado/search.rss?q={termo}&sort=new&restrict_sr=1",
            ]
            for url in fontes_rss:
                nome = "Google News" if "google" in url else "Reddit"
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    titulo = entry.get("title", "")
                    link = entry.get("link", "")
                    conteudo = extrair_conteudo(link)
                    texto_verificar = (titulo + " " + conteudo).lower()
                    if "daikin" not in texto_verificar:
                        continue
                    todas.append({
                        "titulo": titulo,
                        "conteudo": conteudo,
                        "link": link,
                        "fonte": nome,
                        "termo": termo_display,
                        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    })
            videos = buscar_youtube(termo)
            todas.extend(videos)

        for url in BLOGS_RSS:
            nome = url.split("/")[2]
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                titulo = entry.get("title", "")
                link = entry.get("link", "")
                conteudo_blog = extrair_conteudo(link)
                texto_verificar = (titulo + " " + conteudo_blog).lower()
                if "daikin" not in texto_verificar:
                    continue
                todas.append({
                    "titulo": titulo,
                    "conteudo": conteudo_blog,
                    "link": link,
                    "fonte": "Blog",
                    "termo": "blog",
                    "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                })

        novas = [m for m in todas if not ja_visto(m["link"], historico) and m["link"] not in links_ocultos]

        if novas:
            for m in novas:
                m["sentimento"] = analisar_sentimento(m["titulo"], m.get("conteudo", ""))
            historico.extend(novas)
            salvar_json(ARQUIVO_HISTORICO, historico)
            salvar_json(ARQUIVO_MENCOES, novas)
            enviar_email(novas)
    except Exception as e:
        print(f"Erro na varredura: {e}")
    finally:
        varrendo = False

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/mencoes")
def api_mencoes():
    return jsonify(carregar_json(ARQUIVO_MENCOES, []))

@app.route("/api/stats")
def api_stats():
    mencoes = carregar_json(ARQUIVO_MENCOES, [])
    return jsonify({
        "total": len(mencoes),
        "positivo": sum(1 for m in mencoes if m.get("sentimento") == "POSITIVO"),
        "negativo": sum(1 for m in mencoes if m.get("sentimento") == "NEGATIVO"),
        "oportunidade": sum(1 for m in mencoes if m.get("sentimento") == "OPORTUNIDADE"),
        "neutro": sum(1 for m in mencoes if m.get("sentimento") == "NEUTRO"),
        "informativo": sum(1 for m in mencoes if m.get("sentimento") == "INFORMATIVO"),
        "varrendo": varrendo,
        "ultima_atualizacao": datetime.now().strftime("%d/%m/%Y %H:%M")
    })

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
        palavras = t.lower().split()
        if "daikin" not in palavras:
            t = "Daikin " + t
        termos_formatados.append(t.replace(" ", "+"))
    if not termos_formatados:
        termos_formatados = ["Daikin+Brasil"]
    salvar_json(ARQUIVO_TERMOS, termos_formatados)
    return jsonify({"ok": True, "termos": termos_formatados})

@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    dados = request.json
    link = dados.get("link")
    classificacao_correta = dados.get("classificacao_correta")
    motivo = dados.get("motivo", "")
    mencoes = carregar_json(ARQUIVO_MENCOES, [])
    titulo_mencao = ""
    for m in mencoes:
        if m["link"] == link:
            m["sentimento_original"] = m["sentimento"]
            m["sentimento"] = classificacao_correta
            m["feedback"] = motivo
            titulo_mencao = m["titulo"]
            break
    salvar_json(ARQUIVO_MENCOES, mencoes)
    feedbacks = carregar_json(ARQUIVO_FEEDBACKS, [])
    feedbacks.append({
        "titulo": titulo_mencao,
        "link": link,
        "classificacao_original": dados.get("classificacao_original"),
        "classificacao_correta": classificacao_correta,
        "motivo": motivo,
        "data": datetime.now().strftime("%d/%m/%Y %H:%M")
    })
    salvar_json(ARQUIVO_FEEDBACKS, feedbacks)
    return jsonify({"ok": True})

@app.route("/api/varrer", methods=["POST"])
def api_varrer():
    global varrendo
    if varrendo:
        return jsonify({"ok": False, "mensagem": "Varredura já em andamento!"})
    thread = threading.Thread(target=executar_varredura)
    thread.daemon = True
    thread.start()
    return jsonify({"ok": True, "mensagem": "Varredura iniciada!"})

@app.route("/api/ocultar", methods=["POST"])
def api_ocultar():
    dados = request.json
    link = dados.get("link")
    historico = carregar_json(ARQUIVO_HISTORICO, [])
    if not any(h.get("link") == link for h in historico):
        historico.append({"link": link, "oculto": True})
        salvar_json(ARQUIVO_HISTORICO, historico)
    mencoes = carregar_json(ARQUIVO_MENCOES, [])
    mencoes = [m for m in mencoes if m["link"] != link]
    salvar_json(ARQUIVO_MENCOES, mencoes)
    return jsonify({"ok": True})

@app.route("/api/limpar", methods=["POST"])
def api_limpar():
    for arquivo in [ARQUIVO_HISTORICO, ARQUIVO_MENCOES]:
        if os.path.exists(arquivo):
            os.remove(arquivo)
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)