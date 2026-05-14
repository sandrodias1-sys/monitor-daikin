import feedparser
import json
import anthropic
import smtplib
import requests
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from newspaper import Article

from dotenv import load_dotenv
load_dotenv()

CHAVE_API = os.getenv("ANTHROPIC_API_KEY")
CHAVE_YOUTUBE = os.getenv("YOUTUBE_API_KEY")
EMAIL_ENVIO = os.getenv("EMAIL_ENVIO")
EMAIL_SENHA = os.getenv("EMAIL_SENHA")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")

ARQUIVO_HISTORICO = "historico.json"
ARQUIVO_TERMOS = "termos.json"

BLOGS_RSS = [
    "https://www.webarcondicionado.com.br/feed",
    "https://blogdofrio.com.br/feed",
    "https://blogclimatiza.com.br/feed",
    "https://revistadofrio.com.br/feed",
    "https://infohvac.com.br/feed",
]

def carregar_termos():
    if os.path.exists(ARQUIVO_TERMOS):
        with open(ARQUIVO_TERMOS, "r", encoding="utf-8") as f:
            return json.load(f)
    termos_padrao = ["Daikin+Brasil"]
    salvar_termos(termos_padrao)
    return termos_padrao

def salvar_termos(termos):
    with open(ARQUIVO_TERMOS, "w", encoding="utf-8") as f:
        json.dump(termos, f, ensure_ascii=False, indent=2)

def carregar_historico():
    if os.path.exists(ARQUIVO_HISTORICO):
        with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def salvar_historico(historico):
    with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)

def ja_visto(link, historico):
    return any(h["link"] == link for h in historico)

def carregar_exemplos_feedback():
    if not os.path.exists("feedbacks.json"):
        return ""
    with open("feedbacks.json", "r", encoding="utf-8") as f:
        feedbacks = json.load(f)
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
        artigo = Article(url, language="pt")
        artigo.download()
        artigo.parse()
        texto = artigo.text[:2000]
        return texto if texto else ""
    except:
        return ""

def buscar_youtube(termo):
    url = "https://www.googleapis.com/youtube/v3/search"
    termo_limpo = termo.replace("+", " ")
    params = {
        "part": "snippet",
        "q": f"{termo_limpo}",
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
    palavras_termo = [p.lower() for p in termo_limpo.split()]
    for item in dados.get("items", []):
        titulo = item["snippet"]["title"]
        descricao = item["snippet"].get("description", "")
        canal = item["snippet"].get("channelTitle", "")
        texto_completo = (titulo + " " + descricao + " " + canal).lower()
        tem_todos_termos = all(p in texto_completo for p in palavras_termo)
        if not tem_todos_termos:
            continue
        tem_portugues = any(c in texto_completo for c in ["ção", "ões", "ão", "ês", "ár", "é", "ú", "condicionado", "instalação", "climatização"])
        if not tem_portugues and "daikin" not in texto_completo:
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

def analisar_sentimento(titulo, conteudo=""):
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

def enviar_email(novas_mencoes):
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
    <p>Encontramos <strong>{len(novas_mencoes)}</strong> nova(s) menção(ões) desde a última varredura.</p>
    <table style="width:100%; border-collapse:collapse; margin:16px 0">
        <tr>
            <td style="padding:10px; background:#ffebee; border-radius:4px; text-align:center">😟<br><strong>{len(negativas)}</strong><br>Negativas</td>
            <td style="padding:10px; background:#fff3e0; border-radius:4px; text-align:center">💡<br><strong>{len(oportunidades)}</strong><br>Oportunidades</td>
            <td style="padding:10px; background:#e8f5e9; border-radius:4px; text-align:center">😊<br><strong>{len(positivas)}</strong><br>Positivas</td>
            <td style="padding:10px; background:#f5f5f5; border-radius:4px; text-align:center">😐<br><strong>{len(neutras)}</strong><br>Neutras</td>
            <td style="padding:10px; background:#e3f2fd; border-radius:4px; text-align:center">📰<br><strong>{len(informativas)}</strong><br>Informativas</td>
        </tr>
    </table>
    """

    def bloco(titulo_secao, lista, cor):
        if not lista:
            return ""
        html = f"<h3 style='color:{cor}; margin-top:24px'>{titulo_secao}</h3>"
        for m in lista:
            html += f"""
            <div style="border-left:4px solid {cor}; padding:8px 12px; margin:8px 0; background:#fafafa">
                <p style="margin:4px 0"><strong>{m['titulo']}</strong></p>
                <p style="margin:4px 0; color:#666">📍 {m['fonte']} &nbsp;|&nbsp; 📅 {m['data']}</p>
                <p style="margin:4px 0">🔗 <a href="{m['link']}" style="color:#1565c0">{m['link'][:80]}...</a></p>
            </div>"""
        return html

    corpo += bloco("😟 Menções Negativas", negativas, "#e53935")
    corpo += bloco("💡 Oportunidades de Resposta", oportunidades, "#f57c00")
    corpo += bloco("😊 Menções Positivas", positivas, "#43a047")
    corpo += bloco("😐 Menções Neutras", neutras, "#757575")
    corpo += bloco("📰 Informativas", informativas, "#1565c0")
    corpo += "<hr><p><small>Monitor automático de marca Daikin Brasil</small></p>"

    msg.attach(MIMEText(corpo, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as servidor:
        servidor.login(EMAIL_ENVIO, EMAIL_SENHA)
        servidor.sendmail(EMAIL_ENVIO, EMAIL_DESTINO, msg.as_string())
    print(f"✉️ Email enviado para {EMAIL_DESTINO}!")

def buscar_mencoes():
    termos = carregar_termos()
    mencoes = []

    for termo in termos:
        termo_display = termo.replace("+", " ")
        fontes_rss = [
            f"https://news.google.com/rss/search?q={termo}&hl=pt-BR&gl=BR&ceid=BR:pt-419",
            f"https://www.reddit.com/r/brasil/search.rss?q={termo}&sort=new&restrict_sr=1",
            f"https://www.reddit.com/r/arCondicionado/search.rss?q={termo}&sort=new&restrict_sr=1",
        ]
        for url in fontes_rss:
            nome_fonte = "Google News" if "google" in url else "Reddit"
            print(f"📰 [{termo_display}] Buscando em {nome_fonte}...")
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                titulo = entry.get("title", "")
                link = entry.get("link", "")
                print(f"   Lendo: {titulo[:45]}...")
                conteudo = extrair_conteudo(link)
                mencoes.append({
                    "titulo": titulo,
                    "conteudo": conteudo,
                    "link": link,
                    "fonte": nome_fonte,
                    "termo": termo_display,
                    "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                })

        print(f"🎬 [{termo_display}] Buscando no YouTube...")
        videos = buscar_youtube(termo)
        mencoes.extend(videos)

    for url in BLOGS_RSS:
        nome = url.split("/")[2]
        print(f"📝 Buscando em {nome}...")
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:
            titulo = entry.get("title", "")
            link = entry.get("link", "")
            mencoes.append({
                "titulo": titulo,
                "conteudo": extrair_conteudo(link),
                "link": link,
                "fonte": "Blog",
                "termo": "blog",
                "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
            })

    return mencoes

if __name__ == "__main__":
    termos = carregar_termos()
    print(f"🔍 Monitorando termos: {', '.join(t.replace('+', ' ') for t in termos)}\n")
    historico = carregar_historico()
    todas = buscar_mencoes()
    novas = [m for m in todas if not ja_visto(m["link"], historico)]

    if not novas:
        print("✅ Nenhuma menção nova. Nenhum email enviado.")
    else:
        print(f"\n🆕 {len(novas)} menção(ões) nova(s)! Analisando...")
        for m in novas:
            print(f"   Analisando: {m['titulo'][:50]}...")
            m["sentimento"] = analisar_sentimento(m["titulo"], m.get("conteudo", ""))

        negativos = sum(1 for m in novas if m["sentimento"] == "NEGATIVO")
        oportunidades = sum(1 for m in novas if m["sentimento"] == "OPORTUNIDADE")
        positivos = sum(1 for m in novas if m["sentimento"] == "POSITIVO")
        neutros = sum(1 for m in novas if m["sentimento"] == "NEUTRO")
        informativos = sum(1 for m in novas if m["sentimento"] == "INFORMATIVO")

        print(f"\n✓ Análise concluída!")
        print(f"  😟 Negativas:     {negativos}")
        print(f"  💡 Oportunidades: {oportunidades}")
        print(f"  😊 Positivas:     {positivos}")
        print(f"  😐 Neutras:       {neutros}")
        print(f"  📰 Informativas:  {informativos}")

        historico.extend(novas)
        salvar_historico(historico)

        with open("mencoes.json", "w", encoding="utf-8") as f:
            json.dump(novas, f, ensure_ascii=False, indent=2)

        print(f"\n📧 Enviando email...")
        enviar_email(novas)

        print("\n--- RESUMO ---")
        for m in novas:
            emoji = "😟" if m["sentimento"] == "NEGATIVO" else "💡" if m["sentimento"] == "OPORTUNIDADE" else "😊" if m["sentimento"] == "POSITIVO" else "😐" if m["sentimento"] == "NEUTRO" else "📰"
            print(f"{emoji} {m['sentimento']} — [{m['fonte']}] {m['titulo'][:55]}")