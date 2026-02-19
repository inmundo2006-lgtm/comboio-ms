import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import time
import os

# ==========================
# CONFIGURAÇÕES
# ==========================

TENANT_ID = st.secrets["TENANT_ID"]
CLIENT_ID = st.secrets["CLIENT_ID"]
CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
SITE_ID = st.secrets["SITE_ID"]

GRAPH_URL = "https://graph.microsoft.com/v1.0"
CAPACIDADE_MAXIMA = 15000

LISTA_FROTAS_ID = "20F995BE-9493-4516-87D5-C9E794B1164F"

# ==========================
# USUÁRIOS
# ==========================

USUARIOS = {
    "central": {"senha": "central@123", "lista": "9c32dccb-c6e2-4154-a391-e9a493d49bec"},
    "roraima": {"senha": "roraima@123", "lista": "936bf167-ff54-4031-a267-20faa46a1eee"},
    "helicoptero": {"senha": "helico@123", "lista": "0172a697-5094-4495-96d0-25d4f8dddbcb"},
    "cianorte": {"senha": "cianorte@123", "lista": "d11dc55c-31ff-4c81-bed0-27df39a99bf9"},
    "navirai": {"senha": "navirai@123", "lista": "262f461c-9758-484c-b701-e71f2ade1f3e"},
    "maracaju": {"senha": "maracaju@123", "lista": "f67cc033-80fc-4fef-a859-497676b0b539"},
    "reserva": {"senha": "reserva@123", "lista": "31df8ece-779f-4ca5-a1b6-3bf0e46ffd6f"}
}

ARQUIVO_LOGO = "logo_ms.png"
ARQUIVO_VIDEO = "abertura.mp4"

# ==========================
# FUNÇÕES
# ==========================

@st.cache_data(ttl=300)
def obter_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
    r = requests.post(url, data=payload)
    return r.json().get("access_token")

def obter_frotas_sharepoint(token):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LISTA_FROTAS_ID}/items?expand=fields&$top=5000"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers)
    itens = r.json().get("value", [])
    frotas = sorted({i["fields"]["Title"] for i in itens if "Title" in i["fields"]})
    return list(frotas)

def obter_dados(token, LIST_ID):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LIST_ID}/items?expand=fields&$top=2000"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers)
    return [i["fields"] for i in r.json().get("value", [])]

def enviar_dados(token, LIST_ID, dados):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LIST_ID}/items"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"fields": dados}
    requests.post(url, headers=headers, json=payload)

# ==========================
# LOGIN
# ==========================

st.set_page_config("Gestão de Comboio", "🚛", layout="wide")

if "logado" not in st.session_state:
    st.session_state.logado = False

if not st.session_state.logado:
    if os.path.exists(ARQUIVO_LOGO):
        st.image(ARQUIVO_LOGO, width=250)
    if os.path.exists(ARQUIVO_VIDEO):
        st.video(ARQUIVO_VIDEO)

    u = st.text_input("Usuário")
    s = st.text_input("Senha", type="password")

    if st.button("Entrar"):
        if u in USUARIOS and s == USUARIOS[u]["senha"]:
            st.session_state.logado = True
            st.session_state.usuario = u
            st.session_state.LIST_ID = USUARIOS[u]["lista"]
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos")
    st.stop()

# ==========================
# SISTEMA
# ==========================

token = obter_token()
LIST_ID = st.session_state.LIST_ID

dados = obter_dados(token, LIST_ID)
df = pd.DataFrame(dados)

saldo = (
    df[df["Tipo_Operacao"] == "Entrada"]["Litros"].sum()
    - df[df["Tipo_Operacao"] == "Saida"]["Litros"].sum()
) if not df.empty else 0

ult_fim = df.iloc[0]["Comboio_Final"] if not df.empty else 0

frotas = obter_frotas_sharepoint(token)

st.title("🚛 Controle de Frotas e Abastecimento")

aba1, aba2 = st.tabs(["⛽ Abastecer", "📥 Entrada Usina"])

# ==========================
# ABA ABASTECER
# ==========================

with aba1:
    with st.form("saida"):
        frota = st.selectbox("Frota", frotas)
        litros = st.number_input("Litros", min_value=0.0)
        horimetro = st.number_input("Horímetro", min_value=0.0)
        od_final = st.number_input("Relógio Final", min_value=0.0)

        if st.form_submit_button("Salvar"):
            if litros > saldo:
                st.error("Estoque insuficiente")
            else:
                enviar_dados(token, LIST_ID, {
                    "Title": f"Saida - {frota}",
                    "Tipo_Operacao": "Saida",
                    "Frota": frota,
                    "Litros": litros,
                    "Horas_Motor": horimetro,
                    "Comboio_Inicial": ult_fim,
                    "Comboio_Final": od_final
                })
                st.success("Registro salvo")
                time.sleep(1)
                st.rerun()

# ==========================
# ABA ENTRADA
# ==========================

with aba2:
    with st.form("entrada"):
        litros = st.number_input("Litros Recebidos", min_value=0.0)
        if st.form_submit_button("Confirmar"):
            enviar_dados(token, LIST_ID, {
                "Title": "Entrada",
                "Tipo_Operacao": "Entrada",
                "Litros": litros,
                "Comboio_Inicial": ult_fim,
                "Comboio_Final": ult_fim
            })
            st.success("Entrada registrada")
            time.sleep(1)
            st.rerun()
