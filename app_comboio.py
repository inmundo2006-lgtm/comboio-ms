import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime

# ==============================
# CONFIGURAÇÕES DO APP
# ==============================

st.set_page_config(page_title="Controle de Frotas", layout="wide")

TENANT_ID = st.secrets["TENANT_ID"]
CLIENT_ID = st.secrets["CLIENT_ID"]
CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
SITE_ID = st.secrets["SITE_ID"]

# ==============================
# OBTER TOKEN MICROSOFT GRAPH
# ==============================

def obter_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "client_id": CLIENT_ID,
        "scope": "https://graph.microsoft.com/.default",
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    r = requests.post(url, headers=headers, data=data)
    if r.status_code != 200:
        st.error("Erro ao obter token de autenticação.")
        return None

    return r.json().get("access_token")


# ==============================
# DEBUG OPCIONAL: LISTAR DRIVES
# ==============================

def listar_drives():
    token = obter_token()
    if not token:
        st.error("Token inválido.")
        return

    url = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drives"
    headers = {"Authorization": f"Bearer {token}"}

    r = requests.get(url, headers=headers)
    st.write("DRIVES DISPONÍVEIS:", r.json())


# ==============================
# CARREGAR LISTA DE FROTAS
# ==============================

@st.cache_data(ttl=300)
def carregar_frotas():
    token = obter_token()
    if not token:
        return []

    # CAMINHO CORRETO DO ARQUIVO
    caminho = "Shared documents/Arquivo_App_Comboio/Lista_Tratada.xlsx"

    url = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drive/root:/{caminho}:/content"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()

        df = pd.read_excel(r.content)
        return df["FROTA"].dropna().unique().tolist()

    except Exception as e:
        st.error(f"Erro ao carregar frotas: {e}")
        return []


# ==============================
# INTERFACE DO APP
# ==============================

st.title("Controle de Frotas e Abastecimento")

aba = st.tabs(["Abastecer", "Entrada Usina", "Fechamento"])[0]

with aba:
    st.header("Registrar Saída")

    frotas = carregar_frotas()

    frota = st.selectbox("Frota", frotas if frotas else ["Nenhuma frota encontrada"])

    horimetro = st.number_input("Horímetro Atual", min_value=0.0, step=0.1)
    litros = st.number_input("Litros Abastecidos", min_value=0.0, step=0.1)
    relogio_inicial = st.text_input("Relógio Inicial", "01000")
    sugestao = st.text("Sugestão: 1000")
    relogio_final = st.number_input("Relógio Final", min_value=0.0, step=0.1)

    if st.button("Salvar"):
        st.success("Registro salvo com sucesso!")
