import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import time
import os

# ==========================
# CONFIGURAÇÕES DO APLICATIVO
# ==========================

TENANT_ID = st.secrets["TENANT_ID"]
CLIENT_ID = st.secrets["CLIENT_ID"]
CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
SITE_ID = st.secrets["SITE_ID"]

GRAPH_URL = "https://graph.microsoft.com/v1.0"

CAPACIDADE_MAXIMA = 15000

# ==========================
# USUÁRIOS E LISTAS
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

# ==========================
# ARQUIVOS DO SISTEMA
# ==========================
ARQUIVO_LOGO = "logo_ms.png"
ARQUIVO_VIDEO = "abertura.mp4"

# ==========================
# FUNÇÕES DE APOIO
# ==========================

def calcular_diferenca_odometro(inicial, final):
    try:
        inicial, final = float(inicial), float(final)
        return final - inicial if final >= inicial else (100000 - inicial) + final
    except:
        return 0.0

def prever_odometro_final(inicial, litros):
    soma = inicial + litros
    return soma - 100000 if soma > 99999 else soma

@st.cache_data(ttl=60)
def obter_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
    try:
        r = requests.post(url, data=payload)
        r.raise_for_status()
        return r.json().get("access_token")
    except:
        return None

def obter_dados_sharepoint(token, LIST_ID):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LIST_ID}/items?expand=fields&$orderby=fields/Created desc&$top=2000"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers)
        return [item['fields'] for item in r.json().get('value', [])]
    except:
        return []

def enviar_dados_sharepoint(token, LIST_ID, dados):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LIST_ID}/items"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"fields": dados}
    try:
        requests.post(url, headers=headers, json=payload).raise_for_status()
        return True
    except:
        return False

# ==========================
# CARREGAR LISTA DE FROTAS VIA MICROSOFT GRAPH
# ==========================

@st.cache_data(ttl=300)
def carregar_frotas():
    token = obter_token()
    if not token:
        return []

    caminho = "Documentos Compartilhados/ARQUIVO APP COMBOIO/12 - LISTA_TRATADA.xlsx"
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

# ==========================
# DESIGN E LOGIN
# ==========================

st.set_page_config(page_title="Gestão de Comboio", page_icon="🚛", layout="wide")

if 'logado' not in st.session_state:
    st.session_state['logado'] = False

if not st.session_state['logado']:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if os.path.exists(ARQUIVO_LOGO):
            st.image(ARQUIVO_LOGO, width=250)

        st.markdown("<h3 style='text-align: center;'>Sistema de Gestão de Comboio</h3>", unsafe_allow_html=True)

        if os.path.exists(ARQUIVO_VIDEO):
            st.video(ARQUIVO_VIDEO, autoplay=True, loop=True, muted=True)

        st.divider()
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")

        if st.button("ACESSAR", type="primary", use_container_width=True):
            if u in USUARIOS and s == USUARIOS[u]["senha"]:
                st.session_state['logado'] = True
                st.session_state['usuario'] = u
                st.session_state['LIST_ID'] = USUARIOS[u]["lista"]
                st.rerun()
            else:
                st.error("❌ Usuário ou senha inválidos!")
    st.stop()

# ==========================
# SISTEMA PRINCIPAL
# ==========================

LIST_ID = st.session_state["LIST_ID"]

with st.sidebar:
    if os.path.exists(ARQUIVO_LOGO):
        st.image(ARQUIVO_LOGO, width=150)
    st.markdown("---")
    st.write(f"Usuário: **{st.session_state['usuario']}**")
    if st.button("🚪 Sair", use_container_width=True):
        st.session_state['logado'] = False
        st.rerun()

st.title("🚛 Controle de Frotas e Abastecimento")

token = obter_token()
if not token:
    st.error("Erro ao conectar ao SharePoint")
    st.stop()

dados_sp = obter_dados_sharepoint(token, LIST_ID)

colunas = ['Tipo_Operacao', 'Litros', 'Frota', 'Horas_Motor',
           'Comboio_Final', 'Comboio_Inicial', 'Created', 'Entrada_Usina']

df = pd.DataFrame(dados_sp) if dados_sp else pd.DataFrame(columns=colunas)

if not df.empty:
    df['Data_Dt'] = pd.to_datetime(df['Created']).dt.date
    df['Hora'] = pd.to_datetime(df['Created']).dt.strftime('%H:%M')

    try:
        ult_fim = float(df.iloc[0]['Comboio_Final'])
    except:
        ult_fim = 0

    ent = pd.to_numeric(df[df['Tipo_Operacao'] == 'Entrada']['Litros'], errors='coerce').sum()
    sai = pd.to_numeric(df[df['Tipo_Operacao'] == 'Saida']['Litros'], errors='coerce').sum()
    saldo = ent - sai
else:
    ult_fim = 0
    saldo = 0

aba1, aba2, aba3 = st.tabs(["⛽ Abastecer", "📥 Entrada Usina", "📊 Fechamento"])

# ==========================
# ABA 1 — SAÍDA
# ==========================

with aba1:
    st.subheader("Registrar Saída")

    lista_frotas = carregar_frotas()

    with st.form("f_saida", clear_on_submit=True):
        c1, c2 = st.columns(2)

        with c1:
            f = st.selectbox("Frota", lista_frotas)
            h = st.number_input("Horímetro Atual", min_value=0.0)
            l = st.number_input("Litros Abastecidos", min_value=0.0)

        with c2:
            st.info(f"Relógio Inicial: **{ult_fim:05.0f}**")
            sug = prever_odometro_final(ult_fim, l)
            st.caption(f"Sugestão: {sug:.0f}")
            f_od = st.number_input("Relógio Final", min_value=0.0)

        if st.form_submit_button("Salvar", type="primary"):
            if f and l > 0 and f_od > 0:
                enviar_dados_sharepoint(token, LIST_ID, {
                    "Title": f"Saida - {f}",
                    "Tipo_Operacao": "Saida",
                    "Frota": f,
                    "Litros": l,
                    "Horas_Motor": h,
                    "Comboio_Inicial": ult_fim,
                    "Comboio_Final": f_od
                })
                st.success("Registro salvo!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Preencha todos os campos.")

# ==========================
# ABA 2 — ENTRADA
# ==========================

with aba2:
    st.subheader("Entrada de Combustível")

    esp = CAPACIDADE_MAXIMA - saldo
    st.info(f"Espaço disponível: **{esp:,.0f} L**")

    with st.form("f_ent", clear_on_submit=True):
        le = st.number_input("Litros Recebidos", min_value=0.0)
        obs = st.text_input("Observação")

        if st.form_submit_button("Confirmar Entrada"):
            if 0 < le <= esp:
                enviar_dados_sharepoint(token, LIST_ID, {
                    "Title": "Entrada",
                    "Tipo_Operacao": "Entrada",
                    "Litros": le,
                    "Entrada_Usina": le,
                    "Comboio_Inicial": ult_fim,
                    "Comboio_Final": ult_fim
                })
                st.success("Entrada registrada!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Quantidade inválida.")

# ==========================
# ABA 3 — FECHAMENTO
# ==========================

with aba3:
    st.subheader("Fechamento Diário")

    ds = st.date_input("Data", datetime.today())

    df_d = df[df['Data_Dt'] == ds] if not df.empty else pd.DataFrame()

    s_sis = pd.to_numeric(df_d[df_d['Tipo_Operacao'] == 'Saida']['Litros'], errors='coerce').sum()
    s_mec = sum(calcular_diferenca_odometro(r['Comboio_Inicial'], r['Comboio_Final'])
                for _, r in df_d[df_d['Tipo_Operacao'] == 'Saida'].iterrows())

    div = s_mec - s_sis

    st.metric("Total Lançado", f"{s_sis:,.0f} L")
    st.metric("Diferença", f"{div:,.0f} L")

    if not df_d.empty:
        st.dataframe(df_d[['Hora', 'Frota', 'Litros', 'Comboio_Final']], hide_index=True)