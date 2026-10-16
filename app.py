import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
from psycopg2 import IntegrityError
import hashlib
from datetime import datetime, timedelta
import calendar
import google.generativeai as genai
import json
from cryptography.fernet import Fernet
import base64
from fpdf import FPDF
import unicodedata
import yfinance as yf
import PyPDF2
import io

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Maza Finance", layout="wide")

# Compatibilidade segura para st.fragment
fragmento_rapido = getattr(st, "fragment", lambda f: f)

# --- CONEXÃO COM BANCO DE DADOS, IA E CRIPTOGRAFIA (EM CACHE) ---
@st.cache_resource(ttl=300)
def init_connection():
    conn = psycopg2.connect(st.secrets["DATABASE_URL"])
    conn.autocommit = True
    return conn

def obter_cursor():
    global conn
    try:
        if conn.closed != 0:
            st.cache_resource.clear()
            conn = init_connection()
        return conn.cursor()
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        st.cache_resource.clear()
        conn = init_connection()
        return conn.cursor()

conn = init_connection()
c = obter_cursor()

@st.cache_resource
def init_ia():
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        return genai.GenerativeModel('gemini-3.6-flash'), ""
    except Exception as e:
        return None, str(e)

modelo_ia, erro_ia = init_ia()

@st.cache_resource
def init_fernet():
    try:
        return Fernet(st.secrets["ENCRYPTION_KEY"])
    except Exception:
        return None

fernet = init_fernet()

def criptografar(texto):
    if fernet and texto:
        return fernet.encrypt(str(texto).encode()).decode()
    return texto

def descriptografar(texto):
    if fernet and texto:
        try:
            return fernet.decrypt(str(texto).encode()).decode()
        except Exception:
            return texto 
    return texto

# --- OTIMIZAÇÃO: CACHE NAS MIGRAÇÕES E TABELAS ---
@st.cache_resource
def inicializar_banco_dados():
    cur = obter_cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS usuarios (usuario VARCHAR(255) PRIMARY KEY, senha VARCHAR(255))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), categoria VARCHAR(255), valor REAL, descricao TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS metas (usuario VARCHAR(255), categoria VARCHAR(255), limite REAL, PRIMARY KEY (usuario, categoria))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS investimentos (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), valor REAL, descricao TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS va_config (usuario VARCHAR(255) PRIMARY KEY, saldo REAL)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS va_transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), valor REAL, descricao TEXT)''')
    
    cur.execute('''CREATE TABLE IF NOT EXISTS assinaturas (id SERIAL PRIMARY KEY, usuario VARCHAR(255), nome VARCHAR(255), categoria VARCHAR(255), valor REAL, dia_vencimento INTEGER, conta VARCHAR(255), forma_pagamento VARCHAR(50))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS log_assinaturas (id_assinatura INTEGER, mes_ano VARCHAR(20), PRIMARY KEY(id_assinatura, mes_ano))''')

    def check_and_add_column(table, column, col_type, default_val):
        cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' and column_name='{column}'")
        if not cur.fetchone():
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT '{default_val}'")

    check_and_add_column('transacoes', 'conta', 'VARCHAR(255)', 'Geral')
    check_and_add_column('transacoes', 'status', 'VARCHAR(50)', 'Pago')
    check_and_add_column('transacoes', 'forma_pagamento', 'VARCHAR(50)', 'Débito')
    check_and_add_column('investimentos', 'taxa_anual', 'REAL', '0.0')
    
    # NOVAS COLUNAS PARA O HOME BROKER
    check_and_add_column('investimentos', 'ticker', 'VARCHAR(50)', '')
    check_and_add_column('investimentos', 'quantidade', 'REAL', '0.0')

inicializar_banco_dados()

# --- FUNÇÕES DE SEGURANÇA E DADOS ---
def gerar_hash(senha): return hashlib.sha256(str.encode(senha)).hexdigest()
def adicionar_usuario(usuario, senha): c.execute("INSERT INTO usuarios (usuario, senha) VALUES (%s, %s)", (usuario, gerar_hash(senha)))
def verificar_login(usuario, senha):
    c.execute("SELECT * FROM usuarios WHERE usuario = %s AND senha = %s", (usuario, gerar_hash(senha)))
    return c.fetchone()

def adicionar_transacao(usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    desc_segura = criptografar(descricao)
    c.execute("INSERT INTO transacoes (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", 
              (usuario, data, tipo, categoria, valor, desc_segura, conta, status, forma_pagamento))
    buscar_transacoes.clear()

def adicionar_transacoes_lote(lista_lancamentos):
    dados_seguros = [
        (u, dt, tp, cat, val, criptografar(desc), cta, stt, fp)
        for (u, dt, tp, cat, val, desc, cta, stt, fp) in lista_lancamentos
    ]
    c.executemany(
        "INSERT INTO transacoes (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        dados_seguros
    )
    buscar_transacoes.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_transacoes(usuario):
    c.execute("SELECT id, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento FROM transacoes WHERE usuario = %s", (usuario,))
    linhas = c.fetchall()
    linhas_descriptografadas = []
    for linha in linhas:
        linha_lista = list(linha)
        texto_original = linha_lista[5]
        try:
            texto_limpo = descriptografar(texto_original)
            if isinstance(texto_limpo, str) and texto_limpo.startswith("gAAAA"):
                texto_limpo = descriptografar(texto_limpo)
            linha_lista[5] = texto_limpo
        except Exception:
            linha_lista[5] = texto_original
        linhas_descriptografadas.append(linha_lista)
    return pd.DataFrame(linhas_descriptografadas, columns=['ID', 'Data', 'Tipo', 'Categoria', 'Valor', 'Descrição', 'Conta', 'Status', 'Forma de Pagamento'])

def deletar_transacao(id_transacao): 
    c.execute("DELETE FROM transacoes WHERE id = %s", (id_transacao,))
    buscar_transacoes.clear()

def atualizar_transacao(id_transacao, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    desc_segura = criptografar(descricao)
    c.execute("UPDATE transacoes SET data=%s, tipo=%s, categoria=%s, valor=%s, descricao=%s, conta=%s, status=%s, forma_pagamento=%s WHERE id=%s", 
              (data, tipo, categoria, valor, desc_segura, conta, status, forma_pagamento, id_transacao))
    buscar_transacoes.clear()

def marcar_como_paga(id_transacao):
    c.execute("UPDATE transacoes SET status='Pago' WHERE id=%s", (id_transacao,))
    buscar_transacoes.clear()

# FUNÇÕES DE ASSINATURAS RECORRENTES
def adicionar_assinatura(usuario, nome, categoria, valor, dia, conta, forma_pagamento):
    c.execute("INSERT INTO assinaturas (usuario, nome, categoria, valor, dia_vencimento, conta, forma_pagamento) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
              (usuario, nome, categoria, valor, dia, conta, forma_pagamento))
    buscar_assinaturas.clear()
    st.session_state['assinaturas_verificadas'] = False

def atualizar_assinatura(id_ass, nome, categoria, valor, dia, conta, forma_pagamento):
    c.execute("UPDATE assinaturas SET nome=%s, categoria=%s, valor=%s, dia_vencimento=%s, conta=%s, forma_pagamento=%s WHERE id=%s", 
              (nome, categoria, valor, dia, conta, forma_pagamento, id_ass))
    buscar_assinaturas.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_assinaturas(usuario):
    c.execute("SELECT id, nome, categoria, valor, dia_vencimento, conta, forma_pagamento FROM assinaturas WHERE usuario = %s", (usuario,))
    return pd.DataFrame(c.fetchall(), columns=['ID', 'Nome', 'Categoria', 'Valor', 'Dia Venc.', 'Conta', 'Forma de Pagamento'])

def deletar_assinatura(id_ass): 
    c.execute("DELETE FROM assinaturas WHERE id = %s", (id_ass,))
    buscar_assinaturas.clear()

def verificar_e_lancar_assinaturas(usuario):
    hoje = datetime.today()
    mes_ano_atual = hoje.strftime('%m/%Y')
    dia_atual = hoje.day
    
    assinaturas = buscar_assinaturas(usuario)
    if not assinaturas.empty:
        lancou_algo = False
        for _, row in assinaturas.iterrows():
            id_ass = int(row['ID'])
            dia_venc = int(row['Dia Venc.'])
            
            ultimo_dia_mes = calendar.monthrange(hoje.year, hoje.month)[1]
            dia_real = min(dia_venc, ultimo_dia_mes)
            
            if dia_atual >= dia_real:
                c.execute("SELECT 1 FROM log_assinaturas WHERE id_assinatura = %s AND mes_ano = %s", (id_ass, mes_ano_atual))
                if not c.fetchone():
                    data_lanc = f"{hoje.year}-{hoje.month:02d}-{dia_real:02d}"
                    nome_seguro = str(row['Nome']) + " (Assinatura)"
                    desc_segura = criptografar(nome_seguro)
                    
                    c.execute("INSERT INTO transacoes (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                              (usuario, data_lanc, "Despesa", row['Categoria'], row['Valor'], desc_segura, row['Conta'], "Pendente", row['Forma de Pagamento']))
                    
                    c.execute("INSERT INTO log_assinaturas (id_assinatura, mes_ano) VALUES (%s, %s)", (id_ass, mes_ano_atual))
                    lancou_algo = True
                    
        if lancou_algo:
            buscar_transacoes.clear()

# --- FUNÇÕES DE INVESTIMENTOS (ATUALIZADAS PARA O HOME BROKER) ---
def adicionar_investimento(usuario, data, tipo, valor, taxa_anual, descricao, ticker, quantidade):
    desc_segura = criptografar(descricao)
    c.execute("INSERT INTO investimentos (usuario, data, tipo, valor, taxa_anual, descricao, ticker, quantidade) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", 
              (usuario, data, tipo, valor, taxa_anual, desc_segura, ticker, quantidade))
    buscar_investimentos.clear()

def atualizar_investimento(id_inv, data, tipo, valor, taxa_anual, descricao, ticker, quantidade):
    desc_segura = criptografar(descricao)
    c.execute("UPDATE investimentos SET data=%s, tipo=%s, valor=%s, taxa_anual=%s, descricao=%s, ticker=%s, quantidade=%s WHERE id=%s", 
              (data, tipo, valor, taxa_anual, desc_segura, ticker, quantidade, id_inv))
    buscar_investimentos.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_investimentos(usuario):
    c.execute("SELECT id, data, tipo, valor, taxa_anual, descricao, ticker, quantidade FROM investimentos WHERE usuario = %s", (usuario,))
    linhas = c.fetchall()
    linhas_descriptografadas = []
    for linha in linhas:
        linha_lista = list(linha)
        linha_lista[5] = descriptografar(linha_lista[5])
        linhas_descriptografadas.append(linha_lista)
    return pd.DataFrame(linhas_descriptografadas, columns=['ID', 'Data', 'Tipo', 'Valor Original', 'Taxa Anual (%)', 'Descrição', 'Ticker', 'Quantidade'])

def deletar_investimento(id_inv): 
    c.execute("DELETE FROM investimentos WHERE id = %s", (id_inv,))
    buscar_investimentos.clear()

@st.cache_data(ttl=1800, show_spinner=False) # Cache de 30 mins para não bloquear IP do Yahoo Finance
def obter_cotacao(ticker):
    if not ticker or ticker.strip() == "":
        return 0.0
    try:
        tk = yf.Ticker(ticker.strip().upper())
        dados = tk.history(period='1d')
        if not dados.empty:
            return float(dados['Close'].iloc[-1])
        return 0.0
    except Exception:
        return 0.0

# --- FUNÇÕES DE VALE ALIMENTAÇÃO (VA) ---
def salvar_config_va(usuario, saldo): 
    c.execute("INSERT INTO va_config (usuario, saldo) VALUES (%s, %s) ON CONFLICT (usuario) DO UPDATE SET saldo = EXCLUDED.saldo", (usuario, saldo))
    buscar_config_va.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_config_va(usuario):
    c.execute("SELECT saldo FROM va_config WHERE usuario = %s", (usuario,))
    res = c.fetchone()
    return res[0] if res else 0.0

def adicionar_transacao_va(usuario, data, valor, descricao):
    desc_segura = criptografar(descricao)
    c.execute("INSERT INTO va_transacoes (usuario, data, valor, descricao) VALUES (%s, %s, %s, %s)", (usuario, data, valor, desc_segura))
    buscar_transacoes_va.clear()

def atualizar_transacao_va(id_transacao, data, valor, descricao):
    desc_segura = criptografar(descricao)
    c.execute("UPDATE va_transacoes SET data=%s, valor=%s, descricao=%s WHERE id=%s", (data, valor, desc_segura, id_transacao))
    buscar_transacoes_va.clear()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_transacoes_va(usuario):
    c.execute("SELECT id, data, valor, descricao FROM va_transacoes WHERE usuario = %s", (usuario,))
    linhas = c.fetchall()
    linhas_descriptografadas = []
    for linha in linhas:
        linha_lista = list(linha)
        linha_lista[3] = descriptografar(linha_lista[3])
        linhas_descriptografadas.append(linha_lista)
    return pd.DataFrame(linhas_descriptografadas, columns=['ID', 'Data', 'Valor', 'Descrição'])

def deletar_transacao_va(id_transacao): 
    c.execute("DELETE FROM va_transacoes WHERE id = %s", (id_transacao,))
    buscar_transacoes_va.clear()

def add_months(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day).date()

# --- OTIMIZAÇÃO: GERAÇÃO DE PDF EM CACHE ---
def remover_acentos(texto):
    return ''.join(ch for ch in unicodedata.normalize('NFD', str(texto)) if unicodedata.category(ch) != 'Mn')

@st.cache_data(show_spinner=False)
def gerar_pdf_relatorio(df_dados, mes_selecionado, conta_selecionada, entradas_pagas, despesas_pagas):
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Relatorio Financeiro Mensal", ln=True, align='C')
    pdf.set_font("Arial", '', 12)
    
    header_txt = f"Mes de Referencia: {mes_selecionado}"
    if conta_selecionada != "Todas as Contas":
        header_txt += f" | Conta: {conta_selecionada}"
        
    pdf.cell(200, 10, txt=f"{header_txt} | Maza Finance", ln=True, align='C')
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 8, txt=f"Total de Entradas: R$ {entradas_pagas:.2f}", ln=True)
    pdf.cell(200, 8, txt=f"Total de Despesas: R$ {despesas_pagas:.2f}", ln=True)
    pdf.cell(200, 8, txt=f"Saldo Liquido: R$ {entradas_pagas - despesas_pagas:.2f}", ln=True)
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 10)
    pdf.cell(22, 8, "Data", border=1, align='C')
    pdf.cell(22, 8, "Tipo", border=1, align='C')
    pdf.cell(40, 8, "Categoria", border=1, align='C')
    pdf.cell(25, 8, "Valor", border=1, align='C')
    pdf.cell(55, 8, "Descricao", border=1, align='C')
    pdf.cell(26, 8, "Conta", border=1, align='C')
    pdf.ln()

    pdf.set_font("Arial", '', 8)
    for _, row in df_dados.iterrows():
        data_f = pd.to_datetime(row['Data']).strftime('%d/%m/%Y')
        pdf.cell(22, 8, data_f, border=1, align='C')
        pdf.cell(22, 8, remover_acentos(row['Tipo']), border=1, align='C')
        pdf.cell(40, 8, remover_acentos(row['Categoria'])[:20], border=1, align='C')
        pdf.cell(25, 8, f"R$ {row['Valor']:.2f}", border=1, align='C')
        pdf.cell(55, 8, remover_acentos(row['Descrição'])[:35], border=1, align='L')
        pdf.cell(26, 8, remover_acentos(row['Conta'])[:12], border=1, align='C')
        pdf.ln()

    return pdf.output(dest='S').encode('latin-1')

# --- OTIMIZAÇÃO: SIMULADOR ISOLADO EM FRAGMENTO ---
@fragmento_rapido
def renderizar_simulador():
    st.subheader("🔮 Simulador de Rendimentos")
    st.write("Projete o crescimento do seu dinheiro ao longo do tempo com a magia dos juros compostos.")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        val_inicial = st.number_input("Valor Inicial (R$)", min_value=0.0, value=1000.0, step=100.0)
    with col2:
        aporte_mensal = st.number_input("Aporte Mensal (R$)", min_value=0.0, value=200.0, step=50.0)
    with col3:
        taxa_anual = st.number_input("Taxa Anual (%)", min_value=0.0, value=10.5, step=0.5, help="Ex: 10.5% ao ano (Aprox. Selic/CDI atual)")
    with col4:
        anos = st.number_input("Período (Anos)", min_value=1, max_value=50, value=5, step=1)

    taxa_mensal = (1 + taxa_anual / 100) ** (1 / 12) - 1
    meses = int(anos * 12)

    saldo = val_inicial
    total_investido = val_inicial
    dados_grafico = [{'Mês': 0, 'Total Investido': total_investido, 'Saldo Projetado': saldo}]

    for m in range(1, meses + 1):
        saldo = saldo * (1 + taxa_mensal) + aporte_mensal
        total_investido += aporte_mensal
        dados_grafico.append({'Mês': m, 'Total Investido': total_investido, 'Saldo Projetado': saldo})

    df_simulacao = pd.DataFrame(dados_grafico)

    rendimento_juros = saldo - total_investido
    st.markdown("##### Resultado da Simulação")
    rm1, rm2, rm3 = st.columns(3)
    with rm1: st.metric("💰 Total Investido (Do seu bolso)", f"R$ {total_investido:,.2f}")
    with rm2: st.metric("📈 Rendimento (Só em Juros)", f"R$ {rendimento_juros:,.2f}")
    with rm3: st.metric("🏆 Valor Final Estimado", f"R$ {saldo:,.2f}")

    fig_sim = px.area(
        df_simulacao, 
        x='Mês', 
        y=['Total Investido', 'Saldo Projetado'],
        labels={'value': 'Valor (R$)', 'variable': 'Curva'},
        template="plotly_dark",
        color_discrete_map={'Total Investido': '#4B5563', 'Saldo Projetado': '#00CC96'} 
    )
    
    fig_sim.update_layout(
        margin=dict(l=20, r=20, t=20, b=20), 
        hovermode="x unified",
        legend_title_text=''
    )
    st.plotly_chart(fig_sim, use_container_width=True)

# --- SISTEMA DE SESSÃO E CONTADOR DE LIMPEZA DE CAMPOS ---
if 'logado' not in st.session_state: st.session_state['logado'] = False
if 'usuario_atual' not in st.session_state: st.session_state['usuario_atual'] = ""
if 'reset_counter' not in st.session_state: st.session_state['reset_counter'] = 0
if 'assinaturas_verificadas' not in st.session_state: st.session_state['assinaturas_verificadas'] = False
if 'diagnosticos_salvos' not in st.session_state: st.session_state['diagnosticos_salvos'] = {}

rc = st.session_state['reset_counter']

# --- TELA DE LOGIN / CADASTRO ---
if not st.session_state['logado']:
    st.title("🔒 Bem-vindo ao Maza Finance")
    aba_login, aba_cadastro = st.tabs(["Fazer Login", "Criar Conta"])
    
    with aba_login:
        st.subheader("Acesso")
        with st.form("form_login"):
            usuario_login = st.text_input("Utilizador", key="login_user")
            senha_login = st.text_input("Palavra-passe", type="password", key="login_pass")
            botao_entrar = st.form_submit_button("Entrar", type="primary", use_container_width=True)
            
            if botao_entrar:
                user_limpo = usuario_login.strip().lower()
                if verificar_login(user_limpo, senha_login):
                    st.session_state['logado'] = True
                    st.session_state['usuario_atual'] = user_limpo
                    st.session_state['assinaturas_verificadas'] = False
                    st.rerun()
                else: 
                    st.error("Credenciais incorretas!")
                
    with aba_cadastro:
        st.subheader("Nova Conta")
        with st.form("form_cadastro"):
            novo_usuario = st.text_input("Novo Utilizador")
            nova_senha = st.text_input("Nova Palavra-passe", type="password")
            botao_registar = st.form_submit_button("Registar", type="primary", use_container_width=True)
            
            if botao_registar:
                novo_user_limpo = novo_usuario.strip().lower()
                if novo_user_limpo == "" or nova_senha == "": 
                    st.warning("Preencha todos os campos.")
                else:
                    try:
                        adicionar_usuario(novo_user_limpo, nova_senha)
                        st.session_state['logado'] = True
                        st.session_state['usuario_atual'] = novo_user_limpo
                        st.session_state['assinaturas_verificadas'] = False
                        st.success("Conta criada! A carregar...")
                        st.rerun()
                    except IntegrityError: 
                        st.error("Utilizador já existe.")

# --- TELA PRINCIPAL (DASHBOARD) ---
else:
    usuario = st.session_state['usuario_atual']
    mes_atual_sistema = datetime.today().strftime('%m/%Y')
    
    if not st.session_state.get('assinaturas_verificadas', False):
        verificar_e_lancar_assinaturas(usuario)
        st.session_state['assinaturas_verificadas'] = True
    
    st.sidebar.title(f"👤 Olá, {usuario}")
    if st.sidebar.button("Sair (Logout)"):
        st.session_state['logado'] = False
        st.session_state['usuario_atual'] = ""
        st.session_state['assinaturas_verificadas'] = False
        st.rerun()
        
    st.sidebar.markdown("---")
    
    aba_ia, aba_lancamento, aba_assinaturas, aba_va, aba_investimento = st.sidebar.tabs(["🤖 IA", "💸 Manual", "🔄 Assinaturas", "🍔 VA", "📈 Investir"])
    
    with aba_ia:
        aba_ia_chat, aba_ia_pdf = st.tabs(["💬 Chatbot (Texto)", "📂 Extrato Bancário (PDF)"])
        
        with aba_ia_chat:
            st.subheader("🤖 Assistente Inteligente")
            texto_usuario = st.text_input("Digite a transação (Ex: 'Ontem gastei 50 no mercado no crédito pelo Nubank')", key=f"ia_txt_{rc}")
            
            if st.button("Processar com IA", type="primary", use_container_width=True):
                if texto_usuario:
                    with st.spinner("A pensar..."):
                        try:
                            data_hoje_str = datetime.today().strftime('%Y-%m-%d')
                            prompt_sistema = f'''
                            Você é um assistente financeiro. Extraia os dados da transação.
                            A data de hoje é: {data_hoje_str}. Calcule a data correta se o utilizador usar termos relativos.
                            Regras de padronização:
                            - "data": no formato YYYY-MM-DD.
                            - "tipo": apenas "Despesa" ou "Entrada".
                            - "categoria": ["Alimentação", "Transporte", "Viagens", "Moradia", "Lazer", "Saúde", "Educação", "Outros", "Salário", "Freelance", "Rendimento"].
                            - "metodo": ["Pix", "Débito", "Crédito", "Dinheiro", "Boleto"].
                            - "conta": ["Nubank", "Itaú", "Inter", "Bradesco", "Santander", "Caixa", "Banco do Brasil", "Dinheiro", "Geral"].
                            - "status": "Pago" ou "Pendente".
                            
                            Devolva APENAS um JSON válido neste formato (sem markdown ou texto extra):
                            {{"valor": 0.0, "data": "{data_hoje_str}", "categoria": "Alimentação", "tipo": "Despesa", "descricao": "Mercado", "metodo": "Crédito", "conta": "Nubank", "status": "Pago"}}
                            Texto: {texto_usuario}
                            '''
                            resposta = modelo_ia.generate_content(prompt_sistema)
                            texto_limpo = resposta.text.strip().replace("```json", "").replace("```", "")
                            dados_ia = json.loads(texto_limpo)
                            
                            adicionar_transacao(
                                usuario=usuario, data=dados_ia.get("data", data_hoje_str), tipo=dados_ia.get("tipo", "Despesa"),
                                categoria=dados_ia.get("categoria", "Outros"), valor=float(dados_ia.get("valor", 0.0)),
                                descricao=dados_ia.get("descricao", "Lançamento IA"), conta=dados_ia.get("conta", "Geral"), 
                                status=dados_ia.get("status", "Pago"), forma_pagamento=dados_ia.get("metodo", "Débito")
                            )
                            st.session_state['reset_counter'] += 1
                            st.success("Lançamento guardado com sucesso!")
                            st.rerun() 
                        except Exception as e:
                            st.error("Erro ao processar. Tente ser mais claro na descrição.")
                            
        with aba_ia_pdf:
            st.subheader("📄 Leitura de Extrato em PDF")
            st.write("Faça upload do extrato do seu banco em PDF. A IA vai analisar todas as páginas e categorizar as transações automaticamente para si.")
            arquivo_pdf = st.file_uploader("Arraste o PDF do extrato aqui", type=['pdf'])
            
            if st.button("Analisar e Importar Extrato", type="primary", use_container_width=True):
                if arquivo_pdf is not None:
                    with st.spinner("A ler o PDF e a processar dezenas de transações... Isto pode demorar alguns segundos."):
                        try:
                            leitor_pdf = PyPDF2.PdfReader(arquivo_pdf)
                            texto_extrato = ""
                            for pagina in leitor_pdf.pages:
                                texto_extrato += pagina.extract_text()
                                
                            prompt_leitor_pdf = f'''
                            Analise este texto extraído de um extrato bancário.
                            Identifique TODAS as transações financeiras (entradas e saídas de dinheiro).
                            Ignore saldos acumulados, avisos, publicidade ou cabeçalhos.
                            
                            Para cada transação, devolva uma entrada num ARRAY JSON padronizado com as chaves exatas:
                            - "data": YYYY-MM-DD (deduza o ano pelo contexto se faltar).
                            - "tipo": "Despesa" (saídas/débitos) ou "Entrada" (créditos/recebimentos).
                            - "categoria": Classifique de forma inteligente em ["Alimentação", "Transporte", "Moradia", "Lazer", "Saúde", "Educação", "Salário", "Rendimento", "Outros"].
                            - "valor": número flutuante positivo (ex: 15.50).
                            - "descricao": O nome do estabelecimento ou origem limpo e capitalizado.
                            - "metodo": deduza pelo contexto ["Pix", "Débito", "Crédito", "Boleto", "TED/DOC"] ou assuma "Débito".
                            - "conta": Assuma a conta como "Geral" se não for óbvio qual é o banco.
                            - "status": sempre "Pago".
                            
                            DEVOLVA EXCLUSIVAMENTE O ARRAY JSON (sem markdown). Exemplo de formato:
                            [
                              {{"data": "2026-10-05", "tipo": "Despesa", "categoria": "Alimentação", "valor": 45.90, "descricao": "Padaria Silva", "metodo": "Débito", "conta": "Geral", "status": "Pago"}}
                            ]
                            
                            Extrato para análise:
                            {texto_extrato}
                            '''
                            
                            resposta = modelo_ia.generate_content(prompt_leitor_pdf)
                            texto_limpo = resposta.text.strip().replace("```json", "").replace("```", "")
                            lista_transacoes_ia = json.loads(texto_limpo)
                            
                            lote_importacao = []
                            for t in lista_transacoes_ia:
                                lote_importacao.append((
                                    usuario, t.get("data", datetime.today().strftime('%Y-%m-%d')),
                                    t.get("tipo", "Despesa"), t.get("categoria", "Outros"),
                                    float(t.get("valor", 0.0)), t.get("descricao", "Importação PDF"),
                                    t.get("conta", "Geral"), "Pago", t.get("metodo", "Débito")
                                ))
                                
                            if lote_importacao:
                                adicionar_transacoes_lote(lote_importacao)
                                st.success(f"Magia feita! {len(lote_importacao)} transações foram lidas e importadas para o seu Fluxo de Caixa.")
                            else:
                                st.warning("A IA leu o PDF mas não encontrou transações financeiras válidas.")
                        except Exception as e:
                            st.error(f"Erro ao processar o PDF. Certifique-se de que é um extrato de texto legível. Detalhe: {e}")
                else:
                    st.warning("Por favor, faça upload de um ficheiro PDF primeiro.")

    with aba_lancamento:
        tipo_lancamento = st.selectbox("Tipo", ["Despesa", "Entrada"], key="tipo_lanc")
        
        if tipo_lancamento == "Despesa":
            opcoes_categoria = ["Alimentação", "Transporte", "Viagens", "Moradia", "Lazer", "Saúde", "Educação", "Outros"]
        else:
            opcoes_categoria = ["Salário", "Freelance", "Rendimento", "Outros"]
            
        categoria = st.selectbox("Categoria", opcoes_categoria, key="cat_lanc")
        
        conta_lancamento = st.selectbox("Conta", ["Nubank", "Itaú", "Inter", "Bradesco", "Santander", "Caixa", "Banco do Brasil", "Dinheiro", "Outra"], key="conta_lanc")
        forma_pagamento = st.selectbox("Forma de Pagamento", ["Pix", "Débito", "Crédito", "Dinheiro", "Boleto"], key="forma_pag")
        status_lancamento = st.selectbox("Status", ["Pago", "Pendente"], key="status_lanc")
        data_lancamento = st.date_input("Data", datetime.today(), format="DD/MM/YYYY", key="data_lanc")
        valor_lancamento = st.number_input("Valor (R$)", min_value=0.01, format="%.2f", key=f"valor_lanc_{rc}")
        descricao_lancamento = st.text_input("Descrição", key=f"desc_lanc_{rc}")
        
        eh_parcelado = st.checkbox("Compra Parcelada?", key=f"chk_parcela_{rc}") if tipo_lancamento == "Despesa" else False
        parcelas = st.number_input("Parcelas", 2, 72, 2, key=f"num_parcelas_{rc}") if eh_parcelado else 1
        
        if st.button("Guardar Manual", type="primary", use_container_width=True):
            valor_parcela = valor_lancamento / parcelas
            lote_parcelas = []
            for i in range(parcelas):
                desc_parcela = f"{descricao_lancamento} ({i+1}/{parcelas})" if parcelas > 1 else descricao_lancamento
                data_parc = str(add_months(data_lancamento, i) if parcelas > 1 else data_lancamento)
                lote_parcelas.append((usuario, data_parc, tipo_lancamento, categoria, valor_parcela, desc_parcela, conta_lancamento, status_lancamento, forma_pagamento))
            
            adicionar_transacoes_lote(lote_parcelas)
            st.session_state['reset_counter'] += 1
            st.success("Lançamento guardado!")
            st.rerun()
            
    with aba_assinaturas:
        st.subheader("🔄 Nova Assinatura")
        nome_ass = st.text_input("Serviço (Ex: Google, Netflix)", key=f"nome_ass_{rc}")
        val_ass = st.number_input("Mensalidade (R$)", min_value=0.01, format="%.2f", key=f"val_ass_{rc}")
        dia_ass = st.number_input("Dia de Vencimento", min_value=1, max_value=31, value=10, key="dia_ass")
        cat_ass = st.selectbox("Categoria", ["Lazer", "Moradia", "Educação", "Saúde", "Outros"], key="cat_ass")
        conta_ass = st.selectbox("Conta", ["Nubank", "Itaú", "Inter", "Santander", "Caixa", "Geral"], key="conta_ass")
        forma_ass = st.selectbox("Forma de Pagto", ["Crédito", "Débito", "Pix", "Boleto"], key="forma_ass")
        
        if st.button("Registar Serviço", type="primary", use_container_width=True):
            if nome_ass:
                adicionar_assinatura(usuario, nome_ass, cat_ass, val_ass, dia_ass, conta_ass, forma_ass)
                st.session_state['reset_counter'] += 1
                st.success("Registado! Só aparecerá no Extrato no dia do vencimento.")
                st.rerun()
            else:
                st.warning("Preencha o nome do serviço.")

    with aba_va:
        st.markdown("**1. Recarga do Mês**")
        novo_saldo_va = st.number_input("Valor Recebido VA (R$)", min_value=0.0, format="%.2f", value=float(buscar_config_va(usuario)), key="input_saldo_va")
        if st.button("Atualizar VA", use_container_width=True):
            salvar_config_va(usuario, novo_saldo_va)
            st.success("Atualizado!")
            st.rerun()
            
        st.markdown("---")
        data_va = st.date_input("Data Compra", datetime.today(), format="DD/MM/YYYY", key="d_va")
        valor_va = st.number_input("Valor (R$)", 0.01, format="%.2f", key=f"v_va_{rc}")
        desc_va = st.text_input("Estabelecimento", key=f"des_va_{rc}")
        if st.button("Guardar Gasto VA", type="primary", use_container_width=True):
            adicionar_transacao_va(usuario, str(data_va), valor_va, desc_va)
            st.session_state['reset_counter'] += 1
            st.success("Registado!")
            st.rerun()

    # --- NOVO: ABA DE INVESTIMENTOS COM SUPORTE A AÇÕES/CRIPTO E TICKER ---
    with aba_investimento:
        tipo_inv = st.selectbox("Tipo de Ativo", ["Renda Fixa (CDB/LCI)", "Tesouro Direto", "Ações", "FIIs", "Cripto", "Outros"], key="tipo_inv_menu")
        data_inv = st.date_input("Data da Compra", datetime.today(), format="DD/MM/YYYY")
        
        if tipo_inv in ["Ações", "FIIs", "Cripto"]:
            st.info("💡 **Mercado Variável:** O sistema vai ligar-se à bolsa para ler o preço atual deste ativo automaticamente.")
            col_tk1, col_tk2 = st.columns(2)
            with col_tk1:
                ticker_inv = st.text_input("Código / Ticker (Ex: PETR4.SA, BTC-USD)", key=f"tk_inv_{rc}")
            with col_tk2:
                qtd_inv = st.number_input("Quantidade", min_value=0.0001, format="%.4f", key=f"qtd_inv_{rc}")
            
            valor_inv = st.number_input("Valor Total Investido (Do seu bolso, em R$)", 0.01, format="%.2f", key=f"val_inv_side_{rc}")
            taxa_inv = 0.0 # Renda variável não usa juros compostos fixos
        else:
            ticker_inv = ""
            qtd_inv = 0.0
            valor_inv = st.number_input("Valor Investido (R$)", 0.01, format="%.2f", key=f"val_inv_side_{rc}")
            taxa_inv = st.number_input("Taxa Anual Esperada (%)", 0.0, format="%.2f", help="Ex: 10.5 para 10,5% ao ano.", key=f"taxa_inv_side_{rc}")
            
        desc_inv = st.text_input("Descrição / Corretora", key=f"d_inv_{rc}")
        
        if st.button("Guardar Investimento", type="primary", use_container_width=True):
            adicionar_investimento(usuario, str(data_inv), tipo_inv, valor_inv, taxa_inv, desc_inv, ticker_inv, qtd_inv)
            st.session_state['reset_counter'] += 1
            st.success("Investimento guardado na sua carteira!")
            st.rerun()

    # --- CORPO DO DASHBOARD ---
    st.title("📊 Maza Finance")
    
    df_global = buscar_transacoes(usuario)
    
    aba_visao_geral, aba_assinaturas_principal, aba_modulo_va, aba_carteira, aba_saude = st.tabs(["💰 Fluxo de Caixa", "🔄 Assinaturas", "🍔 Vale Alimentação", "💼 Investimentos", "🏆 Saúde Financeira"])
    
    with aba_visao_geral:
        if df_global.empty: 
            st.info("Sem lançamentos. Use o menu para adicionar!")
        else:
            df = df_global.copy()
            df['Valor'] = df['Valor'].astype(float)
            df['Data_dt'] = pd.to_datetime(df['Data'])
            df['MesAno'] = df['Data_dt'].dt.strftime('%m/%Y')
            
            col_filtro1, col_filtro2 = st.columns(2)
            with col_filtro1:
                meses_unicos = df['MesAno'].unique().tolist()
                meses_ordenados = sorted(meses_unicos, key=lambda x: datetime.strptime(x, "%m/%Y"), reverse=False)
                opcoes_mes = ["Todos os Meses"] + meses_ordenados
                idx_mes_padrao = opcoes_mes.index(mes_atual_sistema) if mes_atual_sistema in opcoes_mes else 0
                mes_selecionado = st.selectbox("📅 Mês", opcoes_mes, index=idx_mes_padrao)
            with col_filtro2:
                contas_disponiveis = sorted(df['Conta'].unique().tolist())
                conta_selecionada = st.selectbox("🏦 Conta", ["Todas as Contas"] + contas_disponiveis)
            
            df_filtrado = df.copy()
            if mes_selecionado != "Todos os Meses":
                df_filtrado = df_filtrado[df_filtrado['MesAno'] == mes_selecionado]
            if conta_selecionada != "Todas as Contas":
                df_filtrado = df_filtrado[df_filtrado['Conta'] == conta_selecionada]
            
            df_pendentes = df[df['Status'] == 'Pendente'].copy()
            if mes_selecionado != "Todos os Meses":
                df_pendentes = df_pendentes[df_pendentes['MesAno'] == mes_selecionado]
                
            if not df_pendentes.empty:
                df_pendentes['Data_Real'] = pd.to_datetime(df_pendentes['Data']).dt.date
                hoje = datetime.today().date()
                atrasadas, vencem_hoje, prox = df_pendentes[df_pendentes['Data_Real'] < hoje], df_pendentes[df_pendentes['Data_Real'] == hoje], df_pendentes[(df_pendentes['Data_Real'] > hoje) & (df_pendentes['Data_Real'] <= hoje + timedelta(days=5))]
                
                if not atrasadas.empty or not vencem_hoje.empty or not prox.empty:
                    st.subheader("📅 Central de Vencimentos")
                    c1, c2, c3 = st.columns(3)
                    with c1: 
                        if not atrasadas.empty: st.error(f"🔴 {len(atrasadas)} Atrasadas!\nR$ {atrasadas['Valor'].sum():.2f}")
                    with c2: 
                        if not vencem_hoje.empty: st.warning(f"🟡 {len(vencem_hoje)} Vencem HOJE!\nR$ {vencem_hoje['Valor'].sum():.2f}")
                    with c3: 
                        if not prox.empty: st.info(f"🔵 {len(prox)} em 5 dias\nR$ {prox['Valor'].sum():.2f}")
                    
                    with st.expander("💸 Contas Pendentes (Clique para Dar Baixa)", expanded=True):
                        df_pendentes_ordenado = df_pendentes.sort_values(by='Data_Real')
                        for idx, row in df_pendentes_ordenado.iterrows():
                            data_f = row['Data_Real'].strftime('%d/%m/%Y')
                            
                            if row['Data_Real'] < hoje: icone = "🔴"
                            elif row['Data_Real'] == hoje: icone = "🟡"
                            else: icone = "🔵"
                            
                            col_txt, col_btn = st.columns([4, 1])
                            with col_txt:
                                st.write(f"{icone} **{data_f}** | {row['Descrição']} | **R$ {row['Valor']:.2f}** | {row['Conta']}")
                            with col_btn:
                                if st.button("✅ Dar Baixa", key=f"baixa_{row['ID']}"):
                                    marcar_como_paga(row['ID'])
                                    st.success("Conta paga com sucesso!")
                                    st.rerun()
                    st.markdown("---")

            if not df_filtrado.empty:
                entradas_pagas = df_filtrado[(df_filtrado['Tipo'] == 'Entrada') & (df_filtrado['Status'] == 'Pago')]['Valor'].sum()
                despesas_pagas = df_filtrado[(df_filtrado['Tipo'] == 'Despesa') & (df_filtrado['Status'] == 'Pago')]['Valor'].sum()
                
                entradas_antigas, despesas_antigas = 0.0, 0.0
                if mes_selecionado != "Todos os Meses":
                    try:
                        dt_atual_filtro = datetime.strptime(mes_selecionado, "%m/%Y")
                        mes_passado_str = (dt_atual_filtro.replace(day=1) - timedelta(days=1)).strftime('%m/%Y')
                        df_passado = df[(df['MesAno'] == mes_passado_str) & (df['Status'] == 'Pago')]
                        if conta_selecionada != "Todas as Contas":
                            df_passado = df_passado[df_passado['Conta'] == conta_selecionada]
                        entradas_antigas = df_passado[df_passado['Tipo'] == 'Entrada']['Valor'].sum()
                        despesas_antigas = df_passado[df_passado['Tipo'] == 'Despesa']['Valor'].sum()
                    except Exception:
                        pass
                
                delta_ent = f"R$ {entradas_pagas - entradas_antigas:+.2f} vs mês ant." if mes_selecionado != "Todos os Meses" else None
                delta_desp = f"R$ {despesas_pagas - despesas_antigas:+.2f} vs mês ant." if mes_selecionado != "Todos os Meses" else None

                c1, c2, c3, c4 = st.columns(4)
                with c1: st.metric("Entradas (Pagas)", f"R$ {entradas_pagas:,.2f}", delta=delta_ent, delta_color="normal" if mes_selecionado != "Todos os Meses" else "off")
                with c2: st.metric("Despesas (Pagas)", f"R$ {despesas_pagas:,.2f}", delta=delta_desp, delta_color="inverse" if mes_selecionado != "Todos os Meses" else "off")
                with c3: st.metric("Saldo Atual", f"R$ {entradas_pagas - despesas_pagas:,.2f}")
                with c4: st.metric("⚠️ A Pagar (Pendentes)", f"R$ {df_filtrado[(df_filtrado['Tipo'] == 'Despesa') & (df_filtrado['Status'] == 'Pendente')]['Valor'].sum():,.2f}")
                
                df_desp = df_filtrado[df_filtrado['Tipo'] == 'Despesa']
                with st.expander("📉 Análise de Despesas", expanded=False):
                    if not df_desp.empty:
                        g1, g2 = st.columns(2)
                        res_cat = df_desp.groupby('Categoria')['Valor'].sum().reset_index()
                        with g1: 
                            fig_cat = px.pie(res_cat, values='Valor', names='Categoria', title="Por Categoria", hole=0.6, template="plotly_dark")
                            fig_cat.update_traces(textposition='outside', textinfo='percent+label', marker=dict(line=dict(color='#0E1117', width=2)))
                            fig_cat.update_layout(showlegend=False, margin=dict(t=40, b=40, l=40, r=40))
                            st.plotly_chart(fig_cat, use_container_width=True)
                        with g2: 
                            fig_bar_cat = px.bar(res_cat, x='Categoria', y='Valor', color='Categoria', title="Por Categoria", text_auto='.2f', template="plotly_dark")
                            fig_bar_cat.update_layout(showlegend=False)
                            st.plotly_chart(fig_bar_cat, use_container_width=True)
                        
                        st.markdown("---")
                        
                        df_forma = df_desp.copy()
                        df_forma['Forma Agrupada'] = df_forma['Forma de Pagamento'].apply(lambda x: 'Débito / Pix' if x in ['Débito', 'Pix'] else x)
                        res_forma = df_forma.groupby('Forma Agrupada')['Valor'].sum().reset_index()
                        
                        g3, g4 = st.columns(2)
                        with g3: 
                            fig_forma_pie = px.pie(res_forma, values='Valor', names='Forma Agrupada', title="Crédito vs Débito/Pix", hole=0.6, template="plotly_dark", color_discrete_sequence=px.colors.qualitative.Pastel)
                            fig_forma_pie.update_traces(textposition='outside', textinfo='percent+label', marker=dict(line=dict(color='#0E1117', width=2)))
                            fig_forma_pie.update_layout(showlegend=False, margin=dict(t=40, b=40, l=40, r=40))
                            st.plotly_chart(fig_forma_pie, use_container_width=True)
                        with g4: 
                            fig_bar_forma = px.bar(res_forma, x='Forma Agrupada', y='Valor', color='Forma Agrupada', title="Crédito vs Débito/Pix", text_auto='.2f', template="plotly_dark", color_discrete_sequence=px.colors.qualitative.Pastel)
                            fig_bar_forma.update_layout(showlegend=False)
                            st.plotly_chart(fig_bar_forma, use_container_width=True)
                            
                st.subheader("📋 Extrato")
                
                termo_busca = st.text_input("🔍 Pesquisar no Extrato (ex: Uber, iFood, Salário)", "", key=f"search_extrato_{rc}")
                df_extrato_view = df_filtrado.copy()
                if termo_busca:
                    df_extrato_view = df_extrato_view[df_extrato_view['Descrição'].str.contains(termo_busca, case=False, na=False)]
                    st.info(f"🔍 Encontrados {len(df_extrato_view)} registos para '{termo_busca}' | Total somado: **R$ {df_extrato_view['Valor'].sum():.2f}**")

                df_extrato_view['Data_parsed'] = pd.to_datetime(df_extrato_view['Data'])
                df_extrato_view = df_extrato_view.sort_values(by='Data_parsed', ascending=False)
                df_extrato_view['Data'] = df_extrato_view['Data_parsed'].dt.date

                st.data_editor(
                    df_extrato_view.drop(columns=['Data_dt', 'MesAno', 'Data_Real', 'ID', 'Data_parsed'], errors='ignore'),
                    hide_index=True,
                    use_container_width=True,
                    disabled=True,
                    column_config={
                        "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                        "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f")
                    }
                )

                st.markdown("---")
                st.subheader("📄 Relatório Mensal em PDF")
                st.write("Exporte o seu extrato do mês com o resumo de indicadores para arquivo ou impressão.")
                
                try:
                    df_para_pdf = df_filtrado[['Data', 'Tipo', 'Categoria', 'Valor', 'Descrição', 'Conta']].copy()
                    pdf_bytes = gerar_pdf_relatorio(df_para_pdf, mes_selecionado, conta_selecionada, float(entradas_pagas), float(despesas_pagas))
                    
                    nome_arquivo = f"Maza_Finance_Relatorio_{mes_selecionado.replace('/', '_')}"
                    if conta_selecionada != "Todas as Contas":
                        nome_arquivo += f"_{conta_selecionada}"

                    st.download_button(
                        label="⬇️ Baixar Relatório",
                        data=pdf_bytes,
                        file_name=f"{nome_arquivo}.pdf",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
                except Exception as e:
                    st.error(f"Erro ao gerar PDF: {e}")

                st.markdown("---")
                with st.expander("✏️ Gerir Lançamentos (Editar ou Excluir)", expanded=False):
                    opcoes = df_filtrado['ID'].astype(str) + " - " + df_filtrado['Descrição'] + " (R$ " + df_filtrado['Valor'].map("{:.2f}".format) + ")"
                    escolha = st.selectbox("Selecione o Lançamento pelo ID ou Nome:", opcoes.tolist())
                    
                    if escolha:
                        id_selecionado = int(escolha.split(" - ")[0])
                        linha = df_filtrado[df_filtrado['ID'] == id_selecionado].iloc[0]
                        
                        aba_editar, aba_excluir = st.tabs(["✏️ Atualizar Dados", "🗑️ Apagar Registo"])
                        
                        with aba_editar:
                            c1, c2 = st.columns(2)
                            with c1:
                                n_tipo = st.selectbox("Tipo", ["Despesa", "Entrada"], index=0 if linha['Tipo']=="Despesa" else 1, key=f"tipo_{id_selecionado}")
                                
                                if n_tipo == "Despesa":
                                    ops_cat = ["Alimentação", "Transporte", "Viagens", "Moradia", "Lazer", "Saúde", "Educação", "Outros"]
                                else:
                                    ops_cat = ["Salário", "Freelance", "Rendimento", "Outros"]
                                
                                indice_cat = ops_cat.index(linha['Categoria']) if linha['Categoria'] in ops_cat else len(ops_cat) - 1
                                n_cat = st.selectbox("Categoria", ops_cat, index=indice_cat, key=f"cat_{id_selecionado}")
                                
                                n_valor = st.number_input("Valor (R$)", min_value=0.01, value=float(linha['Valor']), format="%.2f", key=f"val_{id_selecionado}")
                                n_data = st.date_input("Data", pd.to_datetime(linha['Data']).date(), format="DD/MM/YYYY", key=f"data_{id_selecionado}")
                                
                            with c2:
                                n_desc = st.text_input("Descrição", value=linha['Descrição'], key=f"desc_{id_selecionado}")
                                
                                ops_conta = ["Nubank", "Itaú", "Inter", "Bradesco", "Santander", "Caixa", "Banco do Brasil", "Dinheiro", "Outra", "Geral"]
                                n_conta = st.selectbox("Conta", ops_conta, index=ops_conta.index(linha['Conta']) if linha['Conta'] in ops_conta else 9, key=f"conta_{id_selecionado}")
                                
                                n_status = st.selectbox("Status", ["Pago", "Pendente"], index=0 if linha['Status']=="Pago" else 1, key=f"status_{id_selecionado}")
                                
                                ops_forma = ["Pix", "Débito", "Crédito", "Dinheiro", "Boleto"]
                                n_forma = st.selectbox("Forma de Pagamento", ops_forma, index=ops_forma.index(linha['Forma de Pagamento']) if linha['Forma de Pagamento'] in ops_forma else 0, key=f"forma_{id_selecionado}")
                                
                            if st.button("💾 Guardar Alterações", type="primary", use_container_width=True, key=f"btn_salvar_{id_selecionado}"):
                                atualizar_transacao(id_selecionado, str(n_data), n_tipo, n_cat, n_valor, n_desc, n_conta, n_status, n_forma)
                                st.success("Atualizado com sucesso!")
                                st.rerun()
                                
                        with aba_excluir:
                            st.warning(f"Tem a certeza que quer apagar permanentemente **{linha['Descrição']}** (R$ {linha['Valor']:.2f})?")
                            if st.button("Sim, Excluir Lançamento", type="primary", use_container_width=True, key=f"btn_excluir_{id_selecionado}"):
                                deletar_transacao(id_selecionado)
                                st.error("Lançamento apagado!")
                                st.rerun()

    with aba_assinaturas_principal:
        st.subheader("🔄 Gestão de Contas Fixas e Assinaturas")
        st.write("Os serviços registados aqui serão lançados automaticamente no seu Extrato apenas quando chegar o dia de vencimento de cada mês.")
        
        df_ass = buscar_assinaturas(usuario)
        if df_ass.empty:
            st.info("Nenhuma assinatura registada. Use o menu lateral (🔄 Assinaturas) para adicionar a Netflix, Google, Internet, etc.")
        else:
            c1, c2 = st.columns([1, 2])
            with c1:
                st.metric("Total de Custos Fixos (Mês)", f"R$ {df_ass['Valor'].sum():,.2f}")
            with c2:
                st.data_editor(
                    df_ass.drop(columns=['ID'], errors='ignore'),
                    hide_index=True,
                    use_container_width=True,
                    disabled=True,
                    column_config={
                        "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                        "Dia Venc.": st.column_config.NumberColumn("Dia Venc.", format="Dia %d")
                    }
                )
                
            st.markdown("---")
            with st.expander("✏️ Gerir Assinaturas (Editar ou Excluir)", expanded=False):
                ops_ass = df_ass['ID'].astype(str) + " - " + df_ass['Nome'] + " (R$ " + df_ass['Valor'].map("{:.2f}".format) + ")"
                escolha_ass = st.selectbox("Selecione o serviço:", ops_ass.tolist(), key="sel_gestao_ass")
                
                if escolha_ass:
                    id_ass_sel = int(escolha_ass.split(" - ")[0])
                    linha_ass = df_ass[df_ass['ID'] == id_ass_sel].iloc[0]
                    
                    aba_ed_ass, aba_ex_ass = st.tabs(["✏️ Atualizar Dados", "🗑️ Apagar Registo"])
                    
                    with aba_ed_ass:
                        c1_a, c2_a = st.columns(2)
                        with c1_a:
                            n_nome_ass = st.text_input("Serviço", value=linha_ass['Nome'], key=f"n_nome_{id_ass_sel}")
                            n_val_ass = st.number_input("Mensalidade (R$)", min_value=0.01, value=float(linha_ass['Valor']), format="%.2f", key=f"n_val_{id_ass_sel}")
                            n_dia_ass = st.number_input("Dia de Vencimento", min_value=1, max_value=31, value=int(linha_ass['Dia Venc.']), key=f"n_dia_{id_ass_sel}")
                        with c2_a:
                            ops_cat_ass = ["Lazer", "Moradia", "Educação", "Saúde", "Outros"]
                            idx_cat_ass = ops_cat_ass.index(linha_ass['Categoria']) if linha_ass['Categoria'] in ops_cat_ass else 4
                            n_cat_ass = st.selectbox("Categoria", ops_cat_ass, index=idx_cat_ass, key=f"n_cat_{id_ass_sel}")
                            
                            ops_conta_ass = ["Nubank", "Itaú", "Inter", "Santander", "Caixa", "Geral"]
                            idx_conta_ass = ops_conta_ass.index(linha_ass['Conta']) if linha_ass['Conta'] in ops_conta_ass else 5
                            n_conta_ass = st.selectbox("Conta", ops_conta_ass, index=idx_conta_ass, key=f"n_conta_{id_ass_sel}")
                            
                            ops_forma_ass = ["Crédito", "Débito", "Pix", "Boleto"]
                            idx_forma_ass = ops_forma_ass.index(linha_ass['Forma de Pagamento']) if linha_ass['Forma de Pagamento'] in ops_forma_ass else 0
                            n_forma_ass = st.selectbox("Forma de Pagto", ops_forma_ass, index=idx_forma_ass, key=f"n_forma_{id_ass_sel}")
                            
                        if st.button("💾 Guardar Alterações da Assinatura", type="primary", use_container_width=True, key=f"btn_save_ass_{id_ass_sel}"):
                            atualizar_assinatura(id_ass_sel, n_nome_ass, n_cat_ass, n_val_ass, n_dia_ass, n_conta_ass, n_forma_ass)
                            st.success("Assinatura atualizada com sucesso!")
                            st.rerun()
                            
                    with aba_ex_ass:
                        st.warning(f"Tem a certeza que quer apagar permanentemente **{linha_ass['Nome']}**?")
                        if st.button("Sim, Excluir Assinatura", type="primary", use_container_width=True, key=f"btn_del_ass_{id_ass_sel}"):
                            deletar_assinatura(id_ass_sel)
                            st.error("Assinatura removida do sistema!")
                            st.rerun()

    with aba_modulo_va:
        st.subheader("🍔 Vale Alimentação")
        s_va, df_va = buscar_config_va(usuario), buscar_transacoes_va(usuario)
        df_va_f = df_va.copy()
        if not df_va.empty:
            df_va_f['MesAno'] = pd.to_datetime(df_va_f['Data']).dt.strftime('%m/%Y')
            
            meses_va = sorted(df_va_f['MesAno'].unique().tolist(), key=lambda x: datetime.strptime(x, "%m/%Y"), reverse=False)
            opcoes_va = ["Todos"] + meses_va
            idx_va_padrao = opcoes_va.index(mes_atual_sistema) if mes_atual_sistema in opcoes_va else 0
            m_va = st.selectbox("📅 Mês VA", opcoes_va, index=idx_va_padrao)
            df_va_f = df_va_f[df_va_f['MesAno'] == m_va] if m_va != "Todos" else df_va_f
        
        t_gasto = df_va_f['Valor'].sum() if not df_va_f.empty else 0
        c1, c2, c3 = st.columns(3)
        with c1: st.metric("Recarga", f"R$ {s_va:.2f}")
        with c2: st.metric("Gasto", f"R$ {t_gasto:.2f}")
        with c3: st.metric("Disponível", f"R$ {s_va - t_gasto:.2f}")
        
        if s_va > 0:
            pct = min((t_gasto / s_va) * 100, 100)
            st.plotly_chart(px.bar(pd.DataFrame({'S': ['Gasto', 'Disp'], 'P': [pct, 100-pct]}), x='P', y=['VA','VA'], color='S', orientation='h', template="plotly_dark").update_layout(xaxis=dict(range=[0, 100])), use_container_width=True)
            
        if not df_va_f.empty:
            df_va_show = df_va_f.drop(columns=['MesAno'], errors='ignore').copy()
            df_va_show['Data_parsed'] = pd.to_datetime(df_va_show['Data'])
            df_va_show = df_va_show.sort_values(by='Data_parsed', ascending=False)
            df_va_show['Data'] = df_va_show['Data_parsed'].dt.date
            
            st.data_editor(
                df_va_show.drop(columns=['ID', 'Data_parsed'], errors='ignore'),
                hide_index=True,
                use_container_width=True,
                disabled=True,
                column_config={
                    "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                    "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f")
                }
            )
            
            st.markdown("---")
            with st.expander("✏️ Gerir Gastos do VA (Editar ou Excluir)", expanded=False):
                opcoes_va_edit = df_va_f['ID'].astype(str) + " - " + df_va_f['Descrição'] + " (R$ " + df_va_f['Valor'].map("{:.2f}".format) + ")"
                escolha_va_item = st.selectbox("Selecione o Gasto do VA pelo ID ou Nome:", opcoes_va_edit.tolist())
                
                if escolha_va_item:
                    id_va_sel = int(escolha_va_item.split(" - ")[0])
                    linha_va = df_va_f[df_va_f['ID'] == id_va_sel].iloc[0]
                    
                    aba_ed_va, aba_ex_va = st.tabs(["✏️ Atualizar Dados", "🗑️ Apagar Registo"])
                    
                    with aba_ed_va:
                        c1_va, c2_va = st.columns(2)
                        with c1_va:
                            n_val_va = st.number_input("Valor (R$)", min_value=0.01, value=float(linha_va['Valor']), format="%.2f", key=f"val_va_ed_{id_va_sel}")
                            n_dat_va = st.date_input("Data da Compra", pd.to_datetime(linha_va['Data']).date(), format="DD/MM/YYYY", key=f"dat_va_ed_{id_va_sel}")
                        with c2_va:
                            n_des_va = st.text_input("Estabelecimento / Descrição", value=linha_va['Descrição'], key=f"des_va_ed_{id_va_sel}")
                            
                        if st.button("💾 Guardar Alterações do VA", type="primary", use_container_width=True, key=f"btn_save_va_{id_va_sel}"):
                            atualizar_transacao_va(id_va_sel, str(n_dat_va), n_val_va, n_des_va)
                            st.success("Gasto do VA atualizado com sucesso!")
                            st.rerun()
                            
                    with aba_ex_va:
                        st.warning(f"Tem a certeza que quer apagar permanentemente **{linha_va['Descrição']}** (R$ {linha_va['Valor']:.2f})?")
                        if st.button("Sim, Excluir Gasto do VA", type="primary", use_container_width=True, key=f"btn_del_va_{id_va_sel}"):
                            deletar_transacao_va(id_va_sel)
                            st.error("Gasto do VA apagado!")
                            st.rerun()

    # --- NOVO HOME BROKER COM YFINANCE ---
    with aba_carteira:
        st.subheader("💼 Património e Rendimentos (Live)")
        df_inv = buscar_investimentos(usuario)
        
        if df_inv.empty: 
            st.info("Sem investimentos registados na sua carteira.")
        else:
            hoje = datetime.today().date()
            valores_atualizados = []
            lucros = []
            
            with st.spinner("A consultar a bolsa em tempo real..."):
                for idx, row in df_inv.iterrows():
                    valor_orig = float(row['Valor Original'])
                    
                    # Se for mercado variável, vai à internet ler o preço de hoje
                    if row['Tipo'] in ['Ações', 'FIIs', 'Cripto'] and row['Ticker'].strip() != "":
                        preco_live = obter_cotacao(row['Ticker'])
                        if preco_live > 0:
                            valor_atual = float(row['Quantidade']) * preco_live
                        else:
                            valor_atual = valor_orig # Fallback se falhar a internet
                    # Se for Renda Fixa, calcula os juros pelo tempo
                    else:
                        data_investimento = pd.to_datetime(row['Data']).date()
                        dias_passados = (hoje - data_investimento).days
                        if dias_passados < 0: dias_passados = 0
                        taxa_aa = float(row['Taxa Anual (%)'])
                        valor_atual = valor_orig * ((1 + taxa_aa / 100) ** (dias_passados / 365))
                        
                    lucro = valor_atual - valor_orig
                    valores_atualizados.append(round(valor_atual, 2))
                    lucros.append(round(lucro, 2))
                
            df_inv['Valor Atualizado'] = valores_atualizados
            df_inv['Lucro (R$)'] = lucros
            
            total_original = df_inv['Valor Original'].sum()
            total_atual = df_inv['Valor Atualizado'].sum()
            lucro_total = total_atual - total_original
            
            c1, c2, c3 = st.columns(3)
            with c1: st.metric("Total Investido (Bolso)", f"R$ {total_original:,.2f}")
            with c2: st.metric("Saldo Atualizado", f"R$ {total_atual:,.2f}", delta=f"R$ {lucro_total:,.2f} de lucro")
            with c3: 
                pct_lucro = (lucro_total / total_original) * 100 if total_original > 0 else 0
                st.metric("Rentabilidade Global", f"{pct_lucro:.2f}%")
            
            st.markdown("---")
            g1, g2 = st.columns([1, 2])
            with g1: 
                fig_inv = px.pie(df_inv.groupby('Tipo')['Valor Atualizado'].sum().reset_index(), values='Valor Atualizado', names='Tipo', hole=0.6, template="plotly_dark", title="Alocação Atual")
                fig_inv.update_traces(textposition='outside', textinfo='percent+label', marker=dict(line=dict(color='#0E1117', width=2)))
                fig_inv.update_layout(showlegend=False, margin=dict(t=40, b=40, l=40, r=40))
                st.plotly_chart(fig_inv, use_container_width=True)
            with g2: 
                st.write("**As suas posições em aberto:**")
                df_inv_show = df_inv.copy()
                df_inv_show['Data_parsed'] = pd.to_datetime(df_inv_show['Data'])
                df_inv_show = df_inv_show.sort_values(by='Data_parsed', ascending=False)
                df_inv_show['Data'] = df_inv_show['Data_parsed'].dt.date
                
                # Oculta colunas vazias de taxa ou ticker para manter a tabela limpa
                st.data_editor(
                    df_inv_show.drop(columns=['ID', 'Data_parsed'], errors='ignore'),
                    hide_index=True,
                    use_container_width=True,
                    disabled=True,
                    column_config={
                        "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                        "Valor Original": st.column_config.NumberColumn("Valor Original", format="R$ %.2f"),
                        "Taxa Anual (%)": st.column_config.NumberColumn("Taxa An. (%)", format="%.2f%%"),
                        "Quantidade": st.column_config.NumberColumn("Qtd.", format="%.4f"),
                        "Valor Atualizado": st.column_config.NumberColumn("Atualizado", format="R$ %.2f"),
                        "Lucro (R$)": st.column_config.NumberColumn("Lucro", format="R$ %.2f")
                    }
                )

            st.markdown("---")
            with st.expander("✏️ Gerir Investimentos (Editar ou Excluir)", expanded=False):
                opcoes_inv = df_inv['ID'].astype(str) + " - " + df_inv['Descrição'] + " (R$ " + df_inv['Valor Original'].map("{:.2f}".format) + ")"
                escolha_inv = st.selectbox("Selecione o Investimento pelo ID ou Nome:", opcoes_inv.tolist())
                
                if escolha_inv:
                    id_selecionado_inv = int(escolha_inv.split(" - ")[0])
                    linha_inv = df_inv[df_inv['ID'] == id_selecionado_inv].iloc[0]
                    
                    aba_editar_inv, aba_excluir_inv = st.tabs(["✏️ Atualizar Dados", "🗑️ Apagar Registo"])
                    
                    with aba_editar_inv:
                        c1_inv, c2_inv = st.columns(2)
                        with c1_inv:
                            ops_tipo_inv = ["Renda Fixa (CDB/LCI)", "Tesouro Direto", "Ações", "FIIs", "Cripto", "Outros"]
                            n_tipo_inv = st.selectbox("Tipo de Ativo", ops_tipo_inv, index=ops_tipo_inv.index(linha_inv['Tipo']) if linha_inv['Tipo'] in ops_tipo_inv else 0, key=f"tipo_inv_{id_selecionado_inv}")
                            n_valor_inv = st.number_input("Valor Investido (R$)", min_value=0.01, value=float(linha_inv['Valor Original']), format="%.2f", key=f"val_inv_{id_selecionado_inv}")
                            n_tk = st.text_input("Ticker (Ações/Cripto)", value=linha_inv['Ticker'], key=f"tk_{id_selecionado_inv}")
                            n_qtd = st.number_input("Quantidade", value=float(linha_inv['Quantidade']), format="%.4f", key=f"qtd_{id_selecionado_inv}")
                            
                        with c2_inv:
                            n_data_inv = st.date_input("Data do Investimento", pd.to_datetime(linha_inv['Data']).date(), format="DD/MM/YYYY", key=f"data_inv_{id_selecionado_inv}")
                            n_taxa_inv = st.number_input("Taxa Anual Esperada (%)", min_value=0.0, value=float(linha_inv['Taxa Anual (%)']), format="%.2f", key=f"taxa_inv_{id_selecionado_inv}")
                            n_desc_inv = st.text_input("Descrição", value=linha_inv['Descrição'], key=f"desc_inv_{id_selecionado_inv}")
                            
                        if st.button("💾 Guardar Alterações", type="primary", use_container_width=True, key=f"btn_salvar_inv_{id_selecionado_inv}"):
                            atualizar_investimento(id_selecionado_inv, str(n_data_inv), n_tipo_inv, n_valor_inv, n_taxa_inv, n_desc_inv, n_tk, n_qtd)
                            st.success("Investimento atualizado com sucesso!")
                            st.rerun()
                            
                    with aba_excluir_inv:
                        st.warning(f"Tem a certeza que quer apagar permanentemente **{linha_inv['Descrição']}** (R$ {linha_inv['Valor Original']:.2f})?")
                        if st.button("Sim, Excluir Investimento", type="primary", use_container_width=True, key=f"btn_excluir_inv_{id_selecionado_inv}"):
                            deletar_investimento(id_selecionado_inv)
                            st.error("Investimento apagado da carteira!")
                            st.rerun()

        st.markdown("---")
        renderizar_simulador()

    with aba_saude:
        st.subheader("🏆 Raio-X Financeiro")
        if not df_global.empty:
            df_s = df_global.copy()
            df_s['MesAno'] = pd.to_datetime(df_s['Data']).dt.strftime('%m/%Y')
            
            meses_saude = sorted(df_s['MesAno'].unique().tolist(), key=lambda x: datetime.strptime(x, "%m/%Y"), reverse=False)
            idx_saude_padrao = meses_saude.index(mes_atual_sistema) if mes_atual_sistema in meses_saude else len(meses_saude) - 1
            mes_saude_sel = st.selectbox("Mês Saúde", meses_saude, index=idx_saude_padrao)
            df_mes = df_s[df_s['MesAno'] == mes_saude_sel]
            
            e, d = df_mes[df_mes['Tipo'] == 'Entrada']['Valor'].astype(float).sum(), df_mes[df_mes['Tipo'] == 'Despesa']['Valor'].astype(float).sum()
            
            sc = max(0, min(100, 50 + (30 if d <= e else -30) + (20 if (e - d) >= (e * 0.20) else 0) if e > 0 else 0))
            
            if e == 0: st.warning("Adicione Entradas para calcular a saúde.")
            elif sc >= 70: st.success("✅ Saúde Financeira Excelente!")
            elif sc >= 40: st.warning("⚠️ Saúde no limite. Atenção aos gastos.")
            else: st.error("🚨 Estado Crítico. Reduza as despesas!")
            
            fig = go.Figure(go.Indicator(
                mode="gauge+number", 
                value=sc, 
                gauge={
                    'axis': {'range': [None, 100]}, 
                    'steps': [
                        {'range': [0, 40], 'color': "#EF553B"}, 
                        {'range': [40, 70], 'color': "#FFA15A"}, 
                        {'range': [70, 100], 'color': "#00CC96"}
                    ]
                }
            ))
            
            fig.update_layout(
                template="plotly_dark", 
                height=350,
                margin=dict(l=20, r=20, t=30, b=20) 
            )
            
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")
            st.subheader("💡 Diagnóstico com IA")
            
            df_despesas_mes = df_mes[df_mes['Tipo'] == 'Despesa']
            if not df_despesas_mes.empty:
                top_categorias = df_despesas_mes.groupby('Categoria')['Valor'].sum().sort_values(ascending=False).head(3).to_dict()
                detalhe_gastos = f"Os 3 maiores gastos deste mês foram: {top_categorias}"
            else:
                detalhe_gastos = "O utilizador ainda não registou despesas neste mês."

            @st.cache_data(ttl=3600, show_spinner=False)
            def gerar_diagnostico_ia(score, entradas, despesas, top_gastos):
                try:
                    prompt_consultor = f'''
                    Atue como um consultor financeiro experiente.
                    O seu cliente tem uma pontuação de saúde financeira de {score} (escala 0-100).
                    Neste mês: Entradas R$ {entradas:.2f} | Despesas R$ {despesas:.2f}.
                    {top_gastos}
                    
                    Escreva um diagnóstico curto e amigável:
                    1. Explique a pontuação de {score}.
                    2. Aponte os pontos fortes.
                    3. Dê 2 dicas de onde/como melhorar com base nas categorias onde ele mais gastou.
                    
                    Sem markdown exagerado, use bullet points. Fale de forma motivadora.
                    '''
                    resposta = modelo_ia.generate_content(prompt_consultor)
                    return resposta.text
                except Exception as erro:
                    erro_str = str(erro).lower()
                    if "429" in erro_str or "quota" in erro_str:
                        return "⏳ **O Consultor IA está muito requisitado no momento!**\n\nAtingimos o limite temporário de consultas rápidas da Google. Por favor, aguarde cerca de um minuto e navegue pelas outras abas antes de voltar aqui para receber o seu diagnóstico."
                    else:
                        return "🛠 **Sistema em manutenção temporária.**\n\nO seu Consultor de IA está a ser reiniciado. A sua saúde financeira contínua a ser calculada normalmente acima. Tente novamente mais tarde!"

            chave_diag = f"{mes_saude_sel}_{sc}_{e:.2f}_{d:.2f}"
            
            if st.button("✨ Gerar / Atualizar Diagnóstico do Mês com IA", type="primary", use_container_width=True):
                with st.spinner("A gerar a sua análise personalizada..."):
                    st.session_state['diagnosticos_salvos'][mes_saude_sel] = gerar_diagnostico_ia(sc, e, d, detalhe_gastos)
            
            if mes_saude_sel in st.session_state['diagnosticos_salvos']:
                st.info(st.session_state['diagnosticos_salvos'][mes_saude_sel])
            else:
                st.caption("Clique no botão acima quando quiser que o Consultor IA analise os dados deste mês.")
