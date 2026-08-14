import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
import time
import os
import unicodedata
import io

# ==========================
# CONFIGURAÇÕES
# ==========================
TENANT_ID = st.secrets["TENANT_ID"]
CLIENT_ID = st.secrets["CLIENT_ID"]
CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
SITE_ID = st.secrets["SITE_ID"]
LISTA_FROTAS_ID = st.secrets["LISTA_FROTAS_ID"]

GRAPH_URL = "https://graph.microsoft.com/v1.0"
CAPACIDADE_MAXIMA = 15000
ARQUIVO_LOGO = "logo_ms.png"
ARQUIVO_VIDEO = "abertura.mp4"

USUARIOS = st.secrets["usuarios"]

# ==========================
# HORÍMETRO COMPARTILHADO ENTRE COMBOIOS
# ==========================
# Nomes internos (Graph API) das colunas NOVAS que precisam existir na lista
# mestre de Frotas (LISTA_FROTAS_ID) — a mesma lista de onde já vem o dropdown
# de frotas e o TipoMedicao (field_6). Se ao criar as colunas no SharePoint o
# nome interno vier diferente do nome de exibição (como aconteceu com
# TipoMedicao -> field_6), ajuste as duas constantes abaixo para o nome real
# (confira em GET /sites/{site}/lists/{lista}/columns).
COL_HORIMETRO_ATUAL = "HorasMotorAtual"
COL_ORIGEM_ATUAL = "ComboioOrigemAtual"

# Lista explícita (opcional) de todas as listas de comboio, para o relatório
# consolidado. Se não existir em secrets.toml, é deduzida das listas usadas
# pelos logins cadastrados em USUARIOS.
LISTAS_COMBOIO_SECRET = st.secrets.get("LISTAS_COMBOIO")

TZ_LOCAL = timezone(timedelta(hours=-3))  # UTC-3 — Naviraí/MS


def _normalizar(texto):
    """Remove acentos e caixa para comparação — 'Helicóptero', 'HELICOPTERO',
    'helicoptero' etc. todos viram 'helicoptero'."""
    if not texto:
        return ""
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('ASCII')
    return texto.lower()


def eh_helicoptero(frota):
    """True se o NOME da frota contiver 'helicoptero' em qualquer lugar —
    cobre casos como '2503 - HELICOPTERO BELL 407', não só o nome exato."""
    return "helicoptero" in _normalizar(frota)



# ==========================
# FUNÇÕES
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

def formatar_numero_br(valor, casas=0):
    """Formata número no padrão brasileiro: ponto para milhar, vírgula para decimal (ex: 15.000,0)."""
    try:
        texto = f"{float(valor):,.{casas}f}"
        return texto.replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return str(valor)

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

def obter_dados_sharepoint(token, lista):
    # ✅ CORRIGIDO: paginação completa — busca TODOS os registros sem limite
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{lista}/items?expand=fields&$orderby=fields/Created desc&$top=2000"
    headers = {"Authorization": f"Bearer {token}"}
    todos = []
    try:
        while url:
            r = requests.get(url, headers=headers)
            data = r.json()
            todos += [item['fields'] for item in data.get('value', [])]
            url = data.get('@odata.nextLink')  # segue para próxima página se existir
    except:
        pass
    return todos

def enviar_dados_sharepoint(token, lista, dados):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{lista}/items"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"fields": dados}
    try:
        r = requests.post(url, headers=headers, json=payload)
        if not r.ok:
            erro = r.json().get("error", {}).get("message", r.text)
            st.error(f"Erro ao salvar ({r.status_code}): {erro}")
            return False
        return True
    except Exception as e:
        st.error(f"Erro de conexao: {e}")
        return False

def enviar_anexo_sharepoint(token, lista, frota, arquivo):
    """Sobe a foto/PDF da nota fiscal para a biblioteca de documentos do site
    (pasta NotasFiscais) e devolve a URL do arquivo, ou None se não houver
    arquivo ou se o envio falhar (nesse caso o registro é salvo sem anexo)."""
    if arquivo is None:
        return None
    try:
        extensao = arquivo.name.split(".")[-1].lower()
        nome_seguro = f"{lista}_{frota}_{datetime.now(TZ_LOCAL).strftime('%Y%m%d_%H%M%S')}.{extensao}"
        nome_seguro = nome_seguro.replace(" ", "_")
        url = f"{GRAPH_URL}/sites/{SITE_ID}/drive/root:/NotasFiscais/{nome_seguro}:/content"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"}
        r = requests.put(url, headers=headers, data=arquivo.getvalue())
        if r.ok:
            return r.json().get("webUrl")
        st.warning(f"Registro salvo, mas não foi possível enviar a nota fiscal ({r.status_code}).")
        return None
    except Exception as e:
        st.warning(f"Registro salvo, mas houve erro ao enviar a nota fiscal: {e}")
        return None

@st.cache_data(ttl=300)
def carregar_frotas(token):
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LISTA_FROTAS_ID}/items?expand=fields&$top=5000"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers)
        itens = r.json().get("value", [])
        frotas = [i["fields"]["Title"] for i in itens if "Title" in i["fields"]]
        return sorted(set(frotas))
    except:
        return []

@st.cache_data(ttl=300)
def carregar_tipos_medicao(token):
    """Carrega automaticamente do SharePoint: frota → 'H' ou 'KM'"""
    url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LISTA_FROTAS_ID}/items?expand=fields&$top=5000"
    headers = {"Authorization": f"Bearer {token}"}
    tipos = {}
    try:
        r = requests.get(url, headers=headers)
        for item in r.json().get("value", []):
            fields = item.get("fields", {})
            frota = fields.get("Title")
            tipo = fields.get("field_6", "H")  # nome interno real da coluna TipoMedicao
            if frota:
                tipos[frota] = "H" if tipo.upper() in ["H", "HORAS", "HORA"] else "KM"
    except:
        pass
    return tipos

def preparar_dataframe(dados_sp):
    colunas = ['Tipo_Operacao', 'Litros', 'Frota', 'Horas_Motor',
               'Comboio_Final', 'Comboio_Inicial', 'Created', 'Entrada_Usina', 'Observacao']
    if not dados_sp:
        return pd.DataFrame(columns=colunas + ['NotaFiscal_URL', 'Data_Dt', 'Hora'])
    df = pd.DataFrame(dados_sp)
    for col in colunas:
        if col not in df.columns:
            df[col] = 0
    if 'NotaFiscal_URL' not in df.columns:
        df['NotaFiscal_URL'] = ""
    df['NotaFiscal_URL'] = df['NotaFiscal_URL'].fillna("")

    # converte de UTC para UTC-3 (Naviraí/MS) antes de extrair data e hora
    dt_utc = pd.to_datetime(df['Created'], errors='coerce', utc=True)
    dt_local = dt_utc.dt.tz_convert(TZ_LOCAL)
    df['Data_Dt'] = dt_local.dt.date
    df['Hora'] = dt_local.dt.strftime('%H:%M')

    for col in ['Litros', 'Horas_Motor', 'Comboio_Final', 'Comboio_Inicial', 'Entrada_Usina']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df

def obter_ultimo_horimetro(df, frota):
    """Horímetro anterior olhando SOMENTE o histórico da lista do comboio atual.
    Mantido como fallback (frota nova, ou item ainda não migrado na lista mestre) —
    o fluxo normal agora usa obter_horimetro_frota_sp(), que é compartilhado
    entre todos os comboios."""
    if df.empty or not frota:
        return 0.0, None
    # Inclui também Saida_Aeroporto (abastecimento externo do helicóptero) para que
    # o horímetro anterior reflita o último abastecimento, seja via comboio ou aeroporto.
    df_frota = df[(df['Frota'] == frota) & (df['Tipo_Operacao'].isin(['Saida', 'Saida_Aeroporto']))].copy()
    if df_frota.empty:
        return 0.0, None
    df_frota = df_frota.sort_values(by='Created', ascending=False).iloc[0]
    ultimo_h = float(df_frota['Horas_Motor'])
    ultima_data = pd.to_datetime(df_frota['Created'])
    return ultimo_h, ultima_data

def _escapar_odata(valor):
    """Escapa aspas simples para uso seguro dentro de um $filter OData."""
    return str(valor).replace("'", "''")

def obter_horimetro_frota_sp(token, frota):
    """Lê o horímetro ATUAL da frota na lista mestre de Frotas — compartilhado
    entre TODOS os comboios, resolvendo o problema de horas 'congeladas' quando
    mais de um comboio abastece a mesma frota.
    Retorna (horas, comboio_origem, item_id, ultima_data) — horas=None se a
    frota ainda não tiver horímetro registrado nessa lista (aí o app cai no
    fallback local, obter_ultimo_horimetro)."""
    if not frota:
        return None, None, None, None
    filtro = _escapar_odata(frota)
    url = (f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LISTA_FROTAS_ID}/items"
           f"?expand=fields&$filter=fields/Title eq '{filtro}'")
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly",
    }
    try:
        r = requests.get(url, headers=headers)
        itens = r.json().get("value", [])
        if not itens:
            return None, None, None, None
        item = itens[0]
        fields = item.get("fields", {})
        item_id = item.get("id")
        origem = fields.get(COL_ORIGEM_ATUAL)
        modificado = item.get("lastModifiedDateTime")
        ultima_data = None
        if modificado:
            try:
                ultima_data = pd.to_datetime(modificado, utc=True).tz_convert(TZ_LOCAL)
            except Exception:
                ultima_data = None
        horas_raw = fields.get(COL_HORIMETRO_ATUAL)
        if horas_raw in (None, ""):
            return None, origem, item_id, ultima_data
        return float(horas_raw), origem, item_id, ultima_data
    except Exception:
        return None, None, None, None

def atualizar_horimetro_frota_sp(token, frota, horas, comboio_origem):
    """Grava o horímetro mais recente da frota na lista mestre (upsert por
    Title). Deve ser chamada logo após CADA saída/abastecimento salvo com
    sucesso, para que o próximo comboio a abastecer essa frota — seja qual
    for — enxergue o valor certo."""
    if not frota:
        return False
    _, _, item_id, _ = obter_horimetro_frota_sp(token, frota)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"fields": {COL_HORIMETRO_ATUAL: horas, COL_ORIGEM_ATUAL: comboio_origem}}
    try:
        if item_id:
            url = f"{GRAPH_URL}/sites/{SITE_ID}/lists/{LISTA_FROTAS_ID}/items/{item_id}"
            r = requests.patch(url, headers=headers, json=payload)
            return r.ok
        # Não deveria acontecer: toda frota do dropdown já vem dessa mesma
        # lista (carregar_frotas), então o item sempre existe. Se cair aqui,
        # a frota foi digitada fora do padrão — não criamos item novo sozinho.
        return False
    except Exception:
        return False

def obter_listas_comboio():
    """Lista de todas as listas (unidades) de comboio no SharePoint, para o
    relatório consolidado. Usa LISTAS_COMBOIO de secrets.toml se existir;
    senão deduz das listas já usadas pelos logins cadastrados."""
    if LISTAS_COMBOIO_SECRET:
        return sorted(set(LISTAS_COMBOIO_SECRET))
    return sorted(set(v["lista"] for v in USUARIOS.values()))

@st.cache_data(ttl=180)
def carregar_todas_listas_comboio(token):
    """Lê e concatena o histórico de TODOS os comboios (todas as listas), cada
    linha marcada com sua lista de origem. Uso exclusivo do relatório
    consolidado (aba 'Relatório Geral') — não interfere no fluxo individual
    de nenhum comboio, que continua lendo só a própria lista."""
    frames = []
    for nome_lista in obter_listas_comboio():
        dados = obter_dados_sharepoint(token, nome_lista)
        df_lista = preparar_dataframe(dados)
        df_lista['Comboio_Lista'] = nome_lista
        frames.append(df_lista)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)

# ==========================
# DESIGN + LOGIN
# ==========================
st.set_page_config(page_title="Gestão de Comboio", page_icon="🚛", layout="wide")

st.markdown("""
<style>
    .card-stock { padding: 20px; border-radius: 10px; color: white; text-align: center; margin-bottom: 20px; }
    .stVideo { border-radius: 15px; width: 100%; max-height: 450px; }
</style>
""", unsafe_allow_html=True)

if 'logado' not in st.session_state:
    st.session_state['logado'] = False

if not st.session_state['logado']:
    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        if os.path.exists(ARQUIVO_LOGO):
            st.image(ARQUIVO_LOGO, width=250)
        st.markdown("<h3 style='text-align:center;'>Sistema de Gestão de Comboio</h3>", unsafe_allow_html=True)
        if os.path.exists(ARQUIVO_VIDEO):
            st.video(ARQUIVO_VIDEO, autoplay=True, loop=True, muted=True)
        st.divider()
        u = st.text_input("Usuário", placeholder="ex: central, roraima...")
        s = st.text_input("Senha", type="password", placeholder="••••••••")
        if st.button("ACESSAR", type="primary", use_container_width=True):
            usuario = u.lower().strip()
            if usuario in USUARIOS and USUARIOS[usuario]["senha"] == s:
                st.session_state['logado'] = True
                st.session_state['usuario'] = usuario
                st.session_state['lista'] = USUARIOS[usuario]["lista"]
                st.session_state['nome'] = USUARIOS[usuario]["nome"]
                st.rerun()
            else:
                st.error("Usuário ou senha invalidos!")
    st.stop()

# ==========================
# SISTEMA PRINCIPAL
# ==========================
LISTA_ATUAL = st.session_state['lista']
NOME_UNIDADE = st.session_state['nome']

with st.sidebar:
    if os.path.exists(ARQUIVO_LOGO):
        st.image(ARQUIVO_LOGO, width=150)
    st.markdown(f"**{NOME_UNIDADE}**")
    st.markdown("---")
    if st.button("Sair", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.title(f"Controle de Frotas - {NOME_UNIDADE}")

token = obter_token()
if not token:
    st.error("Erro de conexao com Microsoft Graph")
    st.stop()

dados_sp = obter_dados_sharepoint(token, LISTA_ATUAL)
df = preparar_dataframe(dados_sp)
TIPOS = carregar_tipos_medicao(token)

# Saldo do comboio: soma apenas 'Entrada' e 'Saida' (comparação exata de texto).
# Os tipos 'Entrada_Aeroporto' e 'Saida_Aeroporto' (abastecimento externo do
# helicóptero) NÃO entram nessa conta — é assim que o estoque do comboio fica
# imune a esses lançamentos, sem precisar de nenhum filtro extra aqui.
saldo, ult_fim = 0, 0
if not df.empty and 'Tipo_Operacao' in df.columns:
    ent = df[df['Tipo_Operacao'] == 'Entrada']['Litros'].sum()
    sai = df[df['Tipo_Operacao'] == 'Saida']['Litros'].sum()
    saldo = ent - sai
    try:
        ult_fim = float(df.iloc[0]['Comboio_Final'])
    except:
        ult_fim = 0

# ==========================
# ABAS
# ==========================
aba1, aba2, aba3, aba4 = st.tabs(["Abastecer", "Entrada Usina", "Fechamento", "Relatório Geral"])

with aba1:
    st.subheader("Registrar Saida")
    lista_frotas = [""] + carregar_frotas(token)

    if "reset_counter" not in st.session_state:
        st.session_state["reset_counter"] = 0

    f = st.selectbox("Frota", lista_frotas, key=f"frota_{st.session_state['reset_counter']}")
    helicoptero = eh_helicoptero(f)

    tipo_medicao = TIPOS.get(f, "H")
    unidade = "h" if tipo_medicao == "H" else "km"
    label_anterior = "Horímetro Anterior da Frota" if tipo_medicao == "H" else "Odômetro Anterior da Frota"
    label_rodado = "Horas Rodadas" if tipo_medicao == "H" else "Quilômetros Rodados"

    # Horímetro COMPARTILHADO entre todos os comboios: busca primeiro na lista
    # mestre de Frotas (atualizada por qualquer comboio que abasteceu por
    # último). Só cai no histórico local desta lista se a frota ainda não
    # tiver um valor lá (ex.: antes da primeira sincronização).
    horas_global, origem_global, _item_frota_id, data_global = obter_horimetro_frota_sp(token, f)
    if horas_global is not None:
        ultimo_h, ultima_data = horas_global, data_global
        fonte_horimetro = origem_global or "outro comboio"
    else:
        ultimo_h, ultima_data = obter_ultimo_horimetro(df, f)
        fonte_horimetro = NOME_UNIDADE

    origem_aeroporto = False
    if f and helicoptero:
        origem = st.radio(
            "Origem do Abastecimento",
            ["Tanque Base", "Aeroporto (Externo)"],
            horizontal=True,
            key="origem_helicoptero"
        )
        origem_aeroporto = (origem == "Aeroporto (Externo)")
        if origem_aeroporto:
            st.info("✈️ Abastecimento **externo** (fora da base) — não afeta o estoque do tanque base, "
                     "mas as horas continuam sendo registradas normalmente.")
        else:
            st.info("⛽ Abastecimento no **tanque base** — desconta do estoque controlado aqui, igual ao dos caminhões.")

    if f:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.metric(f"**{label_anterior}**", f"{formatar_numero_br(ultimo_h, 1)} {unidade}")
        with col2:
            if ultima_data:
                st.caption(f"Último abastecimento: {ultima_data.strftime('%d/%m/%Y %H:%M')}")
            if horas_global is not None and fonte_horimetro != NOME_UNIDADE:
                st.caption(f"📡 Atualizado por: **{fonte_horimetro}**")

        h = st.number_input(
            f"{label_anterior.replace('Anterior', 'Final (Atual)')}",
            min_value=0.0,
            step=0.1,
            format="%.1f",
            key="horimetro_final"
        )

        diferenca = h - ultimo_h

        horimetro_invalido = False
        st.session_state["horimetro_invalido"] = False

        if diferenca > 0:
            st.success(f"✅ **{label_rodado}:** {formatar_numero_br(diferenca, 1)} {unidade}")

            if tipo_medicao == "H" and ultima_data:
                try:
                    agora = pd.Timestamp.now(tz=TZ_LOCAL).tz_localize(None)
                    ultima_naive = ultima_data.tz_localize(None) if ultima_data.tz is not None else ultima_data
                    horas_reais = (agora - ultima_naive).total_seconds() / 3600
                    if diferenca > horas_reais + 6:
                        st.error(f"⚠️ **Favor conferir novamente!** Apenas ~{formatar_numero_br(horas_reais, 1)}h se passaram desde o último abastecimento, mas o avanço informado foi de {formatar_numero_br(diferenca, 1)}h.")
                        horimetro_invalido = True
                        st.session_state["horimetro_invalido"] = True
                except:
                    pass
        elif diferenca < 0:
            st.error(f"⚠️ **Valor abaixo do esperado!** Tem certeza? Se sim, justifique no campo Observação. (Diferença: {formatar_numero_br(-diferenca, 1)} {unidade})")
        else:
            st.info("Nenhum avanço registrado ainda")

    if origem_aeroporto:
        # ------------------------------------------------------------
        # Helicóptero abastecendo fora da base (ex: aeroporto). Ao salvar,
        # o app grava DOIS lançamentos que se anulam entre si
        # (Entrada_Aeroporto + Saida_Aeroporto) — não usam Comboio_Inicial/
        # Final e não passam pela checagem de saldo do tanque base, já que
        # os tipos são diferentes de 'Entrada'/'Saida'.
        # ------------------------------------------------------------
        with st.form("f_saida_helicoptero", clear_on_submit=True):
            l = st.number_input("Litros Abastecidos (Aeroporto)", min_value=0.0, step=1.0)
            obs = st.text_area(
                "Observacao",
                placeholder="Ex: Abastecimento Aeroporto de Naviraí - NF 1234",
                height=80
            )
            nf_arquivo = st.file_uploader("Nota Fiscal (foto ou PDF) — opcional", type=["jpg", "jpeg", "png", "pdf"])

            if st.form_submit_button("Salvar Registro", type="primary", use_container_width=True):
                if not f:
                    st.error("Selecione uma frota valida.")
                elif st.session_state.get("horimetro_invalido", False):
                    st.error("Corrija o horímetro antes de salvar.")
                elif l <= 0:
                    st.error("Preencha o campo de litros.")
                else:
                    horimetro_final = st.session_state.get("horimetro_final", 0.0)
                    obs_final = obs.strip()

                    with st.spinner("Enviando..."):
                        nf_url = enviar_anexo_sharepoint(token, LISTA_ATUAL, f, nf_arquivo)

                        campos_entrada = {
                            "Title": f"Entrada Aeroporto - {f}",
                            "Tipo_Operacao": "Entrada_Aeroporto",
                            "Frota": f,
                            "Litros": l,
                            "Observacao": obs_final
                        }
                        campos_saida = {
                            "Title": f"Saida Aeroporto - {f}",
                            "Tipo_Operacao": "Saida_Aeroporto",
                            "Frota": f,
                            "Litros": l,
                            "Horas_Motor": horimetro_final,
                            "Observacao": obs_final
                        }
                        if nf_url:
                            campos_entrada["NotaFiscal_URL"] = nf_url
                            campos_saida["NotaFiscal_URL"] = nf_url

                        ok_entrada = enviar_dados_sharepoint(token, LISTA_ATUAL, campos_entrada)
                        ok_saida = False
                        if ok_entrada:
                            ok_saida = enviar_dados_sharepoint(token, LISTA_ATUAL, campos_saida)

                        if ok_entrada and ok_saida:
                            atualizar_horimetro_frota_sp(token, f, horimetro_final, NOME_UNIDADE)
                            st.success("Registrado com sucesso! (Entrada e Saída no estoque do Aeroporto)")
                            time.sleep(1)
                            st.session_state["reset_counter"] += 1
                            st.rerun()
                        elif ok_entrada and not ok_saida:
                            st.warning("A Entrada foi registrada, mas houve falha ao registrar a Saída. "
                                       "Verifique manualmente antes de tentar novamente, para não duplicar o lançamento.")
    else:
        with st.form("f_saida", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                l = st.number_input("Litros Abastecidos", min_value=0.0, step=1.0)
            with c2:
                st.info(f"Relogio Inicial: **{ult_fim:05.0f}**")
                sug = prever_odometro_final(ult_fim, l)
                st.caption(f"Sugestao Relogio: {sug:.0f}")
                f_od = st.number_input("Relogio Final (Lido)", format="%.0f", min_value=0.0)

            obs = st.text_area(
                "Observacao",
                placeholder="Ex: Veiculo terceiro - Transportadora XYZ / Pagamento posterior...",
                height=80
            )
            nf_arquivo = st.file_uploader("Nota Fiscal (foto ou PDF) — opcional", type=["jpg", "jpeg", "png", "pdf"])

            if st.form_submit_button("Salvar Registro", type="primary", use_container_width=True):
                if not f:
                    st.error("Selecione uma frota valida.")
                elif st.session_state.get("horimetro_invalido", False):
                    st.error("Corrija o horímetro antes de salvar.")
                elif saldo <= 0:
                    st.error("Tanque sem estoque disponivel.")
                elif l > saldo:
                    st.error(f"Estoque insuficiente. Saldo atual: {formatar_numero_br(saldo, 0)} L")
                elif l <= 0 or f_od <= 0:
                    st.error("Preencha os campos de litros e relógio final.")
                else:
                    horimetro_final = st.session_state.get("horimetro_final", 0.0)
                    obs_final = obs.strip()

                    with st.spinner("Enviando..."):
                        nf_url = enviar_anexo_sharepoint(token, LISTA_ATUAL, f, nf_arquivo)
                        campos = {
                            "Title": f"Saida - {f}",
                            "Tipo_Operacao": "Saida",
                            "Frota": f,
                            "Litros": l,
                            "Horas_Motor": horimetro_final,
                            "Comboio_Inicial": ult_fim,
                            "Comboio_Final": f_od,
                            "Observacao": obs_final
                        }
                        if nf_url:
                            campos["NotaFiscal_URL"] = nf_url
                        if enviar_dados_sharepoint(token, LISTA_ATUAL, campos):
                            # Atualiza o horímetro compartilhado para que qualquer
                            # outro comboio que abasteça essa frota depois enxergue
                            # este valor, e não um valor antigo/congelado.
                            atualizar_horimetro_frota_sp(token, f, horimetro_final, NOME_UNIDADE)
                            st.success("Registrado com sucesso!")
                            time.sleep(1)
                            st.session_state["reset_counter"] += 1
                            st.rerun()

with aba2:
    st.subheader("Carga do Tanque (Usina)")
    esp = CAPACIDADE_MAXIMA - saldo
    st.info(f"Espaco disponivel no tanque: **{formatar_numero_br(esp, 0)} L**")
    with st.form("f_ent", clear_on_submit=True):
        le = st.number_input("Quantidade Recebida (L)", min_value=0.0)
        o = st.text_input("Observacao / NF")
        nf_arquivo_usina = st.file_uploader("Nota Fiscal (foto ou PDF) — opcional", type=["jpg", "jpeg", "png", "pdf"])
        if st.form_submit_button("Confirmar Entrada", use_container_width=True):
            if 0 < le <= esp:
                nf_url_usina = enviar_anexo_sharepoint(token, LISTA_ATUAL, "Usina", nf_arquivo_usina)
                campos_usina = {
                    "Title": "Entrada",
                    "Tipo_Operacao": "Entrada",
                    "Litros": le,
                    "Entrada_Usina": le,
                    "Observacao": o.strip(),
                    "Comboio_Inicial": ult_fim,
                    "Comboio_Final": ult_fim
                }
                if nf_url_usina:
                    campos_usina["NotaFiscal_URL"] = nf_url_usina
                if enviar_dados_sharepoint(token, LISTA_ATUAL, campos_usina):
                    st.success("Estoque Atualizado!")
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("Quantidade invalida ou acima da capacidade do tanque.")

with aba3:
    st.header("Conferencia do Dia")
    ds = st.date_input("Filtrar Data", datetime.today())

    cor = "#28a745" if saldo > 5000 else "#ffc107" if saldo > 2000 else "#dc3545"
    st.markdown(
        f'<div style="background-color:{cor};" class="card-stock">'
        f'<h2>{formatar_numero_br(saldo, 0)} L</h2>Estoque Disponivel</div>',
        unsafe_allow_html=True
    )

    if df.empty:
        st.info("Nenhum registro encontrado para esta unidade.")
    else:
        df_d = df[df['Data_Dt'] == ds].copy()
        saidas_dia = df_d[df_d['Tipo_Operacao'] == 'Saida']
        s_sis = saidas_dia['Litros'].sum()
        s_mec = sum(
            calcular_diferenca_odometro(r.get('Comboio_Inicial', 0), r.get('Comboio_Final', 0))
            for _, r in saidas_dia.iterrows()
        )
        div = s_mec - s_sis

        col1, col2 = st.columns(2)
        col1.metric(f"Total Lancado ({ds.strftime('%d/%m')})", f"{formatar_numero_br(s_sis, 0)} L")
        col2.metric(
            "Diferenca (Mecanico vs Sistema)",
            f"{formatar_numero_br(div, 0)} L",
            delta="Verificar" if abs(div) > 5 else "OK"
        )

        # Abastecimentos externos (helicóptero via aeroporto) do dia — exibidos à
        # parte, apenas para conferência; não entram no Total Lançado/Diferença
        # acima porque usam Tipo_Operacao diferente ('Saida_Aeroporto').
        aeroporto_dia = df_d[df_d['Tipo_Operacao'] == 'Saida_Aeroporto']
        if not aeroporto_dia.empty:
            total_aero = aeroporto_dia['Litros'].sum()
            st.caption(f"✈️ Abastecimentos via Aeroporto (Helicóptero) neste dia — não contam no estoque do comboio: "
                       f"{formatar_numero_br(total_aero, 0)} L")

        if df_d.empty:
            st.info(f"Nenhum registro no dia {ds.strftime('%d/%m/%Y')}.")
        else:
            st.subheader("Relatorio de Movimentacao")
            colunas_exibir = [c for c in ['Hora', 'Tipo_Operacao', 'Frota', 'Litros', 'Comboio_Inicial', 'Comboio_Final', 'Observacao', 'NotaFiscal_URL'] if c in df_d.columns]
            st.dataframe(
                df_d[colunas_exibir],
                use_container_width=True,
                hide_index=True,
                column_config={"NotaFiscal_URL": st.column_config.LinkColumn("Nota Fiscal", display_text="Abrir")}
            )

        # ==========================
        # MÉDIA DE CONSUMO POR PERÍODO
        # ==========================
        st.divider()
        st.subheader("Média de Consumo por Período (Litros/Hora)")

        frotas_disponiveis = sorted([x for x in df['Frota'].dropna().unique().tolist() if x])
        colf1, colf2, colf3 = st.columns([2, 1, 1])
        with colf1:
            frota_media = st.selectbox("Frota", ["Todas"] + frotas_disponiveis, key="frota_media")
        with colf2:
            data_ini_media = st.date_input("Data Inicial", datetime.today() - timedelta(days=7), key="data_ini_media")
        with colf3:
            data_fim_media = st.date_input("Data Final", datetime.today(), key="data_fim_media")

        # Considera 'Saida' e 'Saida_Aeroporto' juntos: o combustível do
        # helicóptero abastecido fora do comboio precisa entrar na média de
        # litros/hora, mesmo não entrando no estoque do comboio.
        df_periodo = df[
            (df['Tipo_Operacao'].isin(['Saida', 'Saida_Aeroporto'])) &
            (df['Data_Dt'] >= data_ini_media) &
            (df['Data_Dt'] <= data_fim_media)
        ].copy()
        if frota_media != "Todas":
            df_periodo = df_periodo[df_periodo['Frota'] == frota_media]
        df_periodo = df_periodo.sort_values(by='Created')

        if len(df_periodo) < 2:
            st.info("Selecione um período com pelo menos 2 abastecimentos da frota para calcular a média.")
        else:
            litros_periodo = df_periodo['Litros'].sum()
            horimetro_ini = float(df_periodo.iloc[0]['Horas_Motor'])
            horimetro_fim = float(df_periodo.iloc[-1]['Horas_Motor'])
            horas_rodadas = horimetro_fim - horimetro_ini

            colm1, colm2, colm3, colm4 = st.columns(4)
            colm1.metric("Litros no Período", f"{formatar_numero_br(litros_periodo, 0)} L")
            colm2.metric("Horímetro Inicial", formatar_numero_br(horimetro_ini, 1))
            colm3.metric("Horímetro Final", formatar_numero_br(horimetro_fim, 1))
            if horas_rodadas > 0:
                colm4.metric("Média L/h", formatar_numero_br(litros_periodo / horas_rodadas, 2))
            else:
                colm4.metric("Média L/h", "N/A")

with aba4:
    st.header("Relatório Geral — Todos os Comboios")
    st.caption(
        "Consolida o histórico de TODAS as listas de comboio (independente de qual "
        "unidade abasteceu). Não interfere no fluxo individual de nenhum comboio — "
        "é só leitura, sob demanda."
    )

    colg1, colg2, colg3 = st.columns([1, 1, 1])
    with colg1:
        data_ini_geral = st.date_input("Data Inicial", datetime.today() - timedelta(days=30), key="data_ini_geral")
    with colg2:
        data_fim_geral = st.date_input("Data Final", datetime.today(), key="data_fim_geral")
    with colg3:
        st.write("")
        st.write("")
        gerar = st.button("🔄 Gerar Relatório", use_container_width=True)

    if gerar:
        with st.spinner("Lendo todos os comboios..."):
            df_geral = carregar_todas_listas_comboio(token)
        st.session_state["df_geral_cache"] = df_geral

    df_geral = st.session_state.get("df_geral_cache")

    if df_geral is None:
        st.info("Clique em **Gerar Relatório** para ler e consolidar os dados de todos os comboios.")
    elif df_geral.empty:
        st.warning("Nenhum dado encontrado nas listas de comboio configuradas.")
    else:
        if data_ini_geral > data_fim_geral:
            st.error("Data Inicial não pode ser depois da Data Final.")
        else:
            df_periodo_geral = df_geral[
                (df_geral['Tipo_Operacao'].isin(['Saida', 'Saida_Aeroporto'])) &
                (df_geral['Data_Dt'] >= data_ini_geral) &
                (df_geral['Data_Dt'] <= data_fim_geral)
            ].copy()
            df_periodo_geral = df_periodo_geral.sort_values(by='Created')

            if df_periodo_geral.empty:
                st.info("Nenhum abastecimento no período selecionado.")
            else:
                # --------------------------------------------------------
                # Agregado diário: soma de litros por Dia + Frota, juntando
                # abastecimentos de qualquer comboio que atendeu a frota.
                # --------------------------------------------------------
                df_diario = (
                    df_periodo_geral
                    .groupby(['Data_Dt', 'Frota'], as_index=False)['Litros']
                    .sum()
                    .rename(columns={'Litros': 'Litros_Dia'})
                    .sort_values(['Data_Dt', 'Frota'])
                )

                # --------------------------------------------------------
                # Resumo do período: por frota, soma de litros, soma de
                # horas rodadas (horímetro final - inicial dentro do
                # filtro) e média de litros/hora — juntando os
                # abastecimentos de todos os comboios que atenderam a
                # mesma frota nesse intervalo.
                # --------------------------------------------------------
                linhas_resumo = []
                for frota, grupo in df_periodo_geral.groupby('Frota'):
                    litros_total = grupo['Litros'].sum()
                    if len(grupo) >= 2:
                        horas_rodadas = float(grupo.iloc[-1]['Horas_Motor']) - float(grupo.iloc[0]['Horas_Motor'])
                    else:
                        horas_rodadas = 0.0
                    media_lh = (litros_total / horas_rodadas) if horas_rodadas > 0 else None
                    linhas_resumo.append({
                        "Frota": frota,
                        "Litros_Total": litros_total,
                        "Horas_Rodadas": horas_rodadas,
                        "Media_L_por_Hora": media_lh,
                    })
                df_resumo = pd.DataFrame(linhas_resumo).sort_values("Frota")

                st.subheader(f"Agregado Diário ({data_ini_geral.strftime('%d/%m')} a {data_fim_geral.strftime('%d/%m')})")
                st.dataframe(df_diario, use_container_width=True, hide_index=True)

                st.subheader("Resumo do Período por Frota")
                st.dataframe(
                    df_resumo.style.format({
                        "Litros_Total": lambda v: formatar_numero_br(v, 0),
                        "Horas_Rodadas": lambda v: formatar_numero_br(v, 1),
                        "Media_L_por_Hora": lambda v: formatar_numero_br(v, 2) if pd.notna(v) else "N/A",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )

                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_diario.to_excel(writer, sheet_name='Agregado_Diario', index=False)
                    df_resumo.to_excel(writer, sheet_name='Resumo_Periodo', index=False)
                buffer.seek(0)

                st.download_button(
                    "📥 Baixar Excel (Agregado Diário + Resumo do Período)",
                    data=buffer,
                    file_name=f"Relatorio_Comboios_{data_ini_geral.strftime('%Y%m%d')}_{data_fim_geral.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )