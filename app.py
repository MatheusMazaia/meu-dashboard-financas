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

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Mazaia Finance", layout="wide")

# --- CONEXÃO COM BANCO DE DADOS E IA ---
@st.cache_resource(ttl=300)
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

conn = init_connection()

try:
    conn.autocommit = True
    c = conn.cursor()
    c.execute("SELECT 1")
except (psycopg2.OperationalError, psycopg2.InterfaceError):
    st.cache_resource.clear()
    conn = init_connection()
    conn.autocommit = True
    c = conn.cursor()

# Configuração da IA Gemini
erro_ia = ""
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    # 1. Pergunta à Google quais são os modelos válidos na sua conta
    modelos_validos = []
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            modelos_validos.append(m.name)
            
    # 2. Escolhe automaticamente o primeiro modelo disponível
    if modelos_validos:
        modelo_ia = genai.GenerativeModel(modelos_validos[0])
    else:
        modelo_ia = None
        erro_ia = "Nenhum modelo de geração de texto está disponível nesta chave."
        
except Exception as e:
    modelo_ia = None
    erro_ia = str(e)

# --- CRIAÇÃO DE TABELAS E MIGRAÇÕES ---
c.execute('''CREATE TABLE IF NOT EXISTS usuarios (usuario VARCHAR(255) PRIMARY KEY, senha VARCHAR(255))''')
c.execute('''CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), categoria VARCHAR(255), valor REAL, descricao TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS metas (usuario VARCHAR(255), categoria VARCHAR(255), limite REAL, PRIMARY KEY (usuario, categoria))''')
c.execute('''CREATE TABLE IF NOT EXISTS investimentos (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), valor REAL, descricao TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS va_config (usuario VARCHAR(255) PRIMARY KEY, saldo REAL)''')
c.execute('''CREATE TABLE IF NOT EXISTS va_transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), valor REAL, descricao TEXT)''')

def check_and_add_column(table, column, col_type, default_val):
    c.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' and column_name='{column}'")
    if not c.fetchone():
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT '{default_val}'")

check_and_add_column('transacoes', 'conta', 'VARCHAR(255)', 'Geral')
check_and_add_column('transacoes', 'status', 'VARCHAR(50)', 'Pago')
check_and_add_column('transacoes', 'forma_pagamento', 'VARCHAR(50)', 'Débito')

# --- FUNÇÕES DE SEGURANÇA E BANCO ---
def gerar_hash(senha): return hashlib.sha256(str.encode(senha)).hexdigest()
def adicionar_usuario(usuario, senha): c.execute("INSERT INTO usuarios (usuario, senha) VALUES (%s, %s)", (usuario, gerar_hash(senha)))
def verificar_login(usuario, senha):
    c.execute("SELECT * FROM usuarios WHERE usuario = %s AND senha = %s", (usuario, gerar_hash(senha)))
    return c.fetchone()

def adicionar_transacao(usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    c.execute("INSERT INTO transacoes (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", 
              (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento))

def buscar_transacoes(usuario):
    c.execute("SELECT id, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento FROM transacoes WHERE usuario = %s", (usuario,))
    return pd.DataFrame(c.fetchall(), columns=['ID', 'Data', 'Tipo', 'Categoria', 'Valor', 'Descrição', 'Conta', 'Status', 'Forma de Pagamento'])

def deletar_transacao(id_transacao): c.execute("DELETE FROM transacoes WHERE id = %s", (id_transacao,))
def atualizar_transacao(id_transacao, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    c.execute("UPDATE transacoes SET data=%s, tipo=%s, categoria=%s, valor=%s, descricao=%s, conta=%s, status=%s, forma_pagamento=%s WHERE id=%s", 
              (data, tipo, categoria, valor, descricao, conta, status, forma_pagamento, id_transacao))

def salvar_meta(usuario, categoria, limite): c.execute("INSERT INTO metas (usuario, categoria, limite) VALUES (%s, %s, %s) ON CONFLICT (usuario, categoria) DO UPDATE SET limite = EXCLUDED.limite", (usuario, categoria, limite))
def buscar_metas(usuario):
    c.execute("SELECT categoria, limite FROM metas WHERE usuario = %s", (usuario,))
    return dict(c.fetchall())

def adicionar_investimento(usuario, data, tipo, valor, descricao): c.execute("INSERT INTO investimentos (usuario, data, tipo, valor, descricao) VALUES (%s, %s, %s, %s, %s)", (usuario, data, tipo, valor, descricao))
def buscar_investimentos(usuario):
    c.execute("SELECT id, data, tipo, valor, descricao FROM investimentos WHERE usuario = %s", (usuario,))
    return pd.DataFrame(c.fetchall(), columns=['ID', 'Data', 'Tipo', 'Valor', 'Descrição'])
def deletar_investimento(id_inv): c.execute("DELETE FROM investimentos WHERE id = %s", (id_inv,))

def salvar_config_va(usuario, saldo): c.execute("INSERT INTO va_config (usuario, saldo) VALUES (%s, %s) ON CONFLICT (usuario) DO UPDATE SET saldo = EXCLUDED.saldo", (usuario, saldo))
def buscar_config_va(usuario):
    c.execute("SELECT saldo FROM va_config WHERE usuario = %s", (usuario,))
    res = c.fetchone()
    return res[0] if res else 0.0
def adicionar_transacao_va(usuario, data, valor, descricao): c.execute("INSERT INTO va_transacoes (usuario, data, valor, descricao) VALUES (%s, %s, %s, %s)", (usuario, data, valor, descricao))
def buscar_transacoes_va(usuario):
    c.execute("SELECT id, data, valor, descricao FROM va_transacoes WHERE usuario = %s", (usuario,))
    return pd.DataFrame(c.fetchall(), columns=['ID', 'Data', 'Valor', 'Descrição'])
def deletar_transacao_va(id_transacao): c.execute("DELETE FROM va_transacoes WHERE id = %s", (id_transacao,))

def add_months(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day).date()

# --- SISTEMA DE SESSÃO ---
if 'logado' not in st.session_state:
    st.session_state['logado'] = False
if 'usuario_atual' not in st.session_state:
    st.session_state['usuario_atual'] = ""

# --- TELA DE LOGIN / CADASTRO ---
if not st.session_state['logado']:
    st.title("🔒 Bem-vindo ao Mazaia Finance")
    aba_login, aba_cadastro = st.tabs(["Fazer Login", "Criar Conta"])
    
    with aba_login:
        st.subheader("Acesso")
        usuario_login = st.text_input("Utilizador", key="login_user")
        senha_login = st.text_input("Palavra-passe", type="password", key="login_pass")
        if st.button("Entrar"):
            user_limpo = usuario_login.strip().lower()
            if verificar_login(user_limpo, senha_login):
                st.session_state['logado'] = True
                st.session_state['usuario_atual'] = user_limpo
                st.rerun()
            else:
                st.error("Credenciais incorretas!")
                
    with aba_cadastro:
        st.subheader("Nova Conta")
        novo_usuario = st.text_input("Novo Utilizador")
        nova_senha = st.text_input("Nova Palavra-passe", type="password")
        if st.button("Registar"):
            novo_user_limpo = novo_usuario.strip().lower()
            if novo_user_limpo == "" or nova_senha == "":
                st.warning("Preencha todos os campos.")
            else:
                try:
                    adicionar_usuario(novo_user_limpo, nova_senha)
                    st.session_state['logado'] = True
                    st.session_state['usuario_atual'] = novo_user_limpo
                    st.success("Conta criada! A carregar...")
                    st.rerun()
                except IntegrityError: 
                    st.error("Utilizador já existe.")

# --- TELA PRINCIPAL (DASHBOARD) ---
else:
    usuario = st.session_state['usuario_atual']
    
    st.sidebar.title(f"👤 Olá, {usuario}")
    if st.sidebar.button("Sair (Logout)"):
        st.session_state['logado'] = False
        st.session_state['usuario_atual'] = ""
        st.rerun()
        
    st.sidebar.markdown("---")
    
    # Abas no Menu Lateral (AGORA COM IA!)
    aba_ia, aba_lancamento, aba_va, aba_investimento = st.sidebar.tabs(["🤖 IA", "💸 Manual", "🍔 VA", "📈 Investir"])
    
    with aba_ia:
        st.markdown("💬 **Assistente Inteligente**")
        st.info("Ex: 'Gastei 45 de uber hoje no crédito' ou 'Recebi 2000 de salário no Itaú'")
        
        texto_ia = st.chat_input("Digite a transação aqui...")
        if texto_ia:
            if modelo_ia is None:
                st.error("⚠️ API do Gemini não configurada nos Secrets!")
            else:
                with st.spinner("O assistente está a processar..."):
                    prompt_sistema = f"""
                    És um assistente financeiro. Extrai os dados da seguinte frase e devolve APENAS um objeto JSON válido, sem formatação markdown ou texto adicional.
                    Chaves obrigatórias no JSON:
                    - "tipo": ("Despesa" ou "Entrada")
                    - "categoria": (Para despesa: Alimentação, Transporte, Viagens, Moradia, Lazer, Saúde, Educação, Outros. Para entrada: Salário, Freelance, Rendimento, Outros)
                    - "valor": (número float, ex: 45.0)
                    - "descricao": (resumo curto da operação)
                    - "conta": (Nubank, Itaú, Inter, Bradesco, Santander, Caixa, Banco do Brasil, Dinheiro, Outra)
                    - "forma_pagamento": (Pix, Débito, Crédito, Dinheiro, Boleto)
                    - "status": ("Pago" ou "Pendente")
                    
                    Frase do utilizador: "{texto_ia}"
                    """
                    try:
                        resposta = modelo_ia.generate_content(prompt_sistema)
                        texto_json = resposta.text.replace('```json', '').replace('```', '').strip()
                        dados = json.loads(texto_json)
                        
                        # Extração segura: se a IA não encontrar o dado na frase, assume um valor padrão
                        tipo = dados.get('tipo', 'Despesa')
                        categoria = dados.get('categoria', 'Outros')
                        valor = float(dados.get('valor', 0.0))
                        descricao = dados.get('descricao', texto_ia)
                        conta = dados.get('conta', 'Outra') # Se não disser o banco, regista como "Outra"
                        forma_pagamento = dados.get('forma_pagamento', 'Dinheiro')
                        status = dados.get('status', 'Pago')
                        
                        data_hoje = str(datetime.today().date())
                        adicionar_transacao(usuario, data_hoje, tipo, categoria, valor, descricao, conta, status, forma_pagamento)
                        st.success(f"✅ Registado: {descricao} - R$ {valor:.2f}")
                    except Exception as e:
                        # Agora o erro vai mostrar exatamente o que falhou para podermos diagnosticar
                        st.error(f"❌ Não consegui interpretar. Erro técnico: {e}")

    with aba_lancamento:
        tipo_lancamento = st.selectbox("Tipo", ["Despesa", "Entrada"], key="tipo_lanc")
        if tipo_lancamento == "Despesa":
            categoria = st.selectbox("Categoria", ["Alimentação", "Transporte", "Viagens", "Moradia", "Lazer", "Saúde", "Educação", "Outros"], key="cat_lanc")
        else:
            categoria = st.selectbox("Categoria", ["Salário", "Freelance", "Rendimento", "Outros"], key="cat_lanc")
            
        conta_lancamento = st.selectbox("Conta / Instituição", ["Nubank", "Itaú", "Inter", "Bradesco", "Santander", "Caixa", "Banco do Brasil", "Dinheiro", "Outra"], key="conta_lanc")
        forma_pagamento = st.selectbox("Forma de Pagamento", ["Pix", "Débito", "Crédito", "Dinheiro", "Boleto"], key="forma_pag")
        status_lancamento = st.selectbox("Status", ["Pago", "Pendente"], key="status_lanc")
            
        data_lancamento = st.date_input("Data", datetime.today(), format="DD/MM/YYYY", key="data_lanc")
        valor_lancamento = st.number_input("Valor (R$)", min_value=0.01, format="%.2f", key="valor_lanc")
        descricao_lancamento = st.text_input("Descrição", key="desc_lanc")
        
        parcelas = 1
        if tipo_lancamento == "Despesa":
            eh_parcelado = st.checkbox("Compra Parcelada?", key="chk_parcela")
            if eh_parcelado:
                parcelas = st.number_input("Número de Parcelas", min_value=2, max_value=72, value=2, step=1, key="num_parcelas")
                st.info(f"Serão gerados {parcelas} lançamentos de R$ {(valor_lancamento/parcelas):.2f}")
        
        if st.button("Guardar Manual", type="primary", use_container_width=True):
            if parcelas == 1:
                adicionar_transacao(usuario, str(data_lancamento), tipo_lancamento, categoria, valor_lancamento, descricao_lancamento, conta_lancamento, status_lancamento, forma_pagamento)
            else:
                valor_parcela = valor_lancamento / parcelas
                for i in range(parcelas):
                    data_parcela = add_months(data_lancamento, i)
                    desc_parcela = f"{descricao_lancamento} ({i+1}/{parcelas})"
                    adicionar_transacao(usuario, str(data_parcela), tipo_lancamento, categoria, valor_parcela, desc_parcela, conta_lancamento, status_lancamento, forma_pagamento)
            st.success("Lançamento guardado!")
            st.rerun()

    with aba_va:
        st.markdown("**1. Recarga do Mês**")
        saldo_atual_va = buscar_config_va(usuario)
        novo_saldo_va = st.number_input("Valor Recebido VA (R$)", min_value=0.0, format="%.2f", value=float(saldo_atual_va), key="input_saldo_va")
        if st.button("Atualizar VA", use_container_width=True):
            salvar_config_va(usuario, novo_saldo_va)
            st.success("Recarga atualizada!")
            st.rerun()
            
        st.markdown("---")
        st.markdown("**2. Gasto VA**")
        data_va = st.date_input("Data Compra", datetime.today(), format="DD/MM/YYYY", key="data_va")
        valor_va = st.number_input("Valor Compra (R$)", min_value=0.01, format="%.2f", key="valor_va")
        desc_va = st.text_input("Estabelecimento", key="desc_va")
        if st.button("Guardar Gasto VA", type="primary", use_container_width=True):
            adicionar_transacao_va(usuario, str(data_va), valor_va, desc_va)
            st.success("Gasto registado!")
            st.rerun()

    with aba_investimento:
        tipo_inv = st.selectbox("Tipo de Investimento", ["Renda Fixa (CDB/LCI)", "Tesouro Direto", "Ações", "Fundos Imobiliários (FIIs)", "Criptomoedas", "Previdência", "Outros"])
        data_inv = st.date_input("Data Aplicação", datetime.today(), format="DD/MM/YYYY", key="data_inv")
        valor_inv = st.number_input("Valor Investido (R$)", min_value=0.01, format="%.2f", key="valor_inv")
        desc_inv = st.text_input("Descrição", key="desc_inv")
        if st.button("Guardar Investimento", type="primary", use_container_width=True):
            adicionar_investimento(usuario, str(data_inv), tipo_inv, valor_inv, desc_inv)
            st.success("Investimento guardado!")
            st.rerun()

    # --- CORPO DO DASHBOARD ---
    st.title("📊 Mazaia Finance")
    
    aba_visao_geral, aba_modulo_va, aba_carteira, aba_saude = st.tabs(["💰 Fluxo de Caixa", "🍔 Vale Alimentação", "💼 Investimentos", "🏆 Saúde Financeira"])
    
    with aba_visao_geral:
        df = buscar_transacoes(usuario)
        
        if df.empty:
            st.info("Sem lançamentos. Use o menu lateral (IA ou Manual) para adicionar!")
        else:
            df['Valor'] = df['Valor'].astype(float)
            df['Data_dt'] = pd.to_datetime(df['Data'])
            df['MesAno'] = df['Data_dt'].dt.strftime('%m/%Y')
            lista_meses = ["Todos os Meses"] + sorted(df['MesAno'].unique().tolist(), reverse=True)
            
            col_filtro, _ = st.columns([1, 3])
            with col_filtro:
                mes_selecionado = st.selectbox("📅 Mês", lista_meses)
            
            # --- Central de Vencimentos ---
            hoje = datetime.today().date()
            df_pendentes = df[df['Status'] == 'Pendente'].copy()
            if not df_pendentes.empty:
                df_pendentes['Data_Real'] = pd.to_datetime(df_pendentes['Data']).dt.date
                atrasadas = df_pendentes[df_pendentes['Data_Real'] < hoje]
                vencem_hoje = df_pendentes[df_pendentes['Data_Real'] == hoje]
                proximos_dias = df_pendentes[(df_pendentes['Data_Real'] > hoje) & (df_pendentes['Data_Real'] <= hoje + timedelta(days=5))]
                
                if not atrasadas.empty or not vencem_hoje.empty or not proximos_dias.empty:
                    st.subheader("📅 Central de Vencimentos")
                    col_v1, col_v2, col_v3 = st.columns(3)
                    with col_v1:
                        if not atrasadas.empty: st.error(f"🔴 {len(atrasadas)} Atrasadas!\nR$ {atrasadas['Valor'].sum():.2f}")
                    with col_v2:
                        if not vencem_hoje.empty: st.warning(f"🟡 {len(vencem_hoje)} Vencem HOJE!\nR$ {vencem_hoje['Valor'].sum():.2f}")
                    with col_v3:
                        if not proximos_dias.empty: st.info(f"🔵 {len(proximos_dias)} nos próximos 5 dias\nR$ {proximos_dias['Valor'].sum():.2f}")
                    st.markdown("---")

            if mes_selecionado != "Todos os Meses":
                df_filtrado = df[df['MesAno'] == mes_selecionado]
            else:
                df_filtrado = df
                
            if not df_filtrado.empty:
                entradas_pagas = df_filtrado[(df_filtrado['Tipo'] == 'Entrada') & (df_filtrado['Status'] == 'Pago')]['Valor'].sum()
                despesas_pagas = df_filtrado[(df_filtrado['Tipo'] == 'Despesa') & (df_filtrado['Status'] == 'Pago')]['Valor'].sum()
                saldo_real = entradas_pagas - despesas_pagas
                contas_a_pagar = df_filtrado[(df_filtrado['Tipo'] == 'Despesa') & (df_filtrado['Status'] == 'Pendente')]['Valor'].sum()
                
                col1, col2, col3, col4 = st.columns(4)
                with col1: st.metric("Entradas", f"R$ {entradas_pagas:,.2f}")
                with col2: st.metric("Despesas", f"R$ {despesas_pagas:,.2f}")
                with col3: st.metric("Saldo Atual", f"R$ {saldo_real:,.2f}")
                with col4: st.metric("⚠️ A Pagar", f"R$ {contas_a_pagar:,.2f}")
                    
                st.markdown("---")
                df_despesas = df_filtrado[df_filtrado['Tipo'] == 'Despesa']
                
                with st.expander("📉 Análise de Despesas", expanded=False):
                    col_graf_d1, col_graf_d2 = st.columns(2)
                    with col_graf_d1:
                        if not df_despesas.empty:
                            resumo_desp = df_despesas.groupby('Categoria')['Valor'].sum().reset_index()
                            st.plotly_chart(px.pie(resumo_desp, values='Valor', names='Categoria', hole=0.5, template="plotly_dark"), use_container_width=True)
                    with col_graf_d2:
                        if not df_despesas.empty:
                            st.plotly_chart(px.bar(resumo_desp, x='Categoria', y='Valor', text_auto='.2f', template="plotly_dark"), use_container_width=True)
                            
                st.markdown("---")
                st.subheader("📋 Extrato Detalhado")
                df_editavel = df_filtrado.copy()
                df_editavel['Data'] = pd.to_datetime(df_editavel['Data']).dt.date
                df_editavel = df_editavel.drop(columns=['Data_dt', 'MesAno', 'Data_Real'], errors='ignore')
                
                st.data_editor(df_editavel, hide_index=True, use_container_width=True, disabled=True)

    with aba_modulo_va:
        st.subheader("🍔 Vale Alimentação")
        saldo_configurado = buscar_config_va(usuario)
        df_va = buscar_transacoes_va(usuario)
        
        if not df_va.empty:
            df_va['Data_dt'] = pd.to_datetime(df_va['Data'])
            df_va['MesAno'] = df_va['Data_dt'].dt.strftime('%m/%Y')
            mes_va_selecionado = st.selectbox("📅 Mês VA", ["Todos os Meses"] + sorted(df_va['MesAno'].unique().tolist(), reverse=True))
            df_va_filtrado = df_va[df_va['MesAno'] == mes_va_selecionado] if mes_va_selecionado != "Todos os Meses" else df_va
        else:
            df_va_filtrado = pd.DataFrame(columns=['ID', 'Data', 'Valor', 'Descrição'])
            
        total_gasto_va = df_va_filtrado['Valor'].sum() if not df_va_filtrado.empty else 0
        saldo_disponivel_va = saldo_configurado - total_gasto_va
        
        col_va1, col_va2, col_va3 = st.columns(3)
        with col_va1: st.metric("Recarga", f"R$ {saldo_configurado:.2f}")
        with col_va2: st.metric("Gasto", f"R$ {total_gasto_va:.2f}")
        with col_va3: st.metric("Disponível", f"R$ {saldo_disponivel_va:.2f}")
            
        st.markdown("---")
        if saldo_configurado > 0:
            pct_gasto = (total_gasto_va / saldo_configurado) * 100
            pct_restante = 100 - pct_gasto if pct_gasto <= 100 else 0
            df_bar_va = pd.DataFrame({'Status': ['Gasto', 'Disponível'], 'Porcentagem': [pct_gasto, pct_restante], 'Texto': [f"{pct_gasto:.1f}%", f"{pct_restante:.1f}%"]}) if pct_gasto <= 100 else pd.DataFrame({'Status': ['Estourado'], 'Porcentagem': [100], 'Texto': [f"{pct_gasto:.1f}%"]})
            cores_va = {'Gasto': '#EF553B', 'Disponível': '#00CC96', 'Estourado': '#EF553B'}
            fig_bar_va = px.bar(df_bar_va, x='Porcentagem', y=['VA']*len(df_bar_va), color='Status', orientation='h', text='Texto', color_discrete_map=cores_va, template="plotly_dark")
            fig_bar_va.update_layout(xaxis=dict(range=[0, 100]))
            st.plotly_chart(fig_bar_va, use_container_width=True)
            
        if not df_va_filtrado.empty:
            df_va_edit = df_va_filtrado.copy()
            df_va_edit['Data'] = pd.to_datetime(df_va_edit['Data']).dt.date
            st.data_editor(df_va_edit.drop(columns=['Data_dt', 'MesAno'], errors='ignore'), hide_index=True, use_container_width=True, disabled=True)

    with aba_carteira:
        st.subheader("💼 Património")
        df_inv = buscar_investimentos(usuario)
        if df_inv.empty:
            st.info("Ainda não tem investimentos.")
        else:
            st.metric("Total Investido", f"R$ {df_inv['Valor'].sum():,.2f}")
            col_inv1, col_inv2 = st.columns([1, 1])
            with col_inv1: st.plotly_chart(px.pie(df_inv.groupby('Tipo')['Valor'].sum().reset_index(), values='Valor', names='Tipo', hole=0.4, template="plotly_dark"), use_container_width=True)
            with col_inv2: 
                df_inv['Data'] = pd.to_datetime(df_inv['Data']).dt.date
                st.data_editor(df_inv, hide_index=True, use_container_width=True, disabled=True)

    with aba_saude:
        st.subheader("🏆 Raio-X Financeiro")
        df_saude = buscar_transacoes(usuario)
        if not df_saude.empty:
            df_saude['Valor'] = df_saude['Valor'].astype(float)
            df_saude['Data_dt'] = pd.to_datetime(df_saude['Data'])
            df_saude['MesAno'] = df_saude['Data_dt'].dt.strftime('%m/%Y')
            
            mes_analise = st.selectbox("Escolha o mês", sorted(df_saude['MesAno'].unique().tolist(), reverse=True), key="mes_saude")
            df_mes = df_saude[df_saude['MesAno'] == mes_analise]
            
            score = 50
            entradas_s = df_mes[df_mes['Tipo'] == 'Entrada']['Valor'].sum()
            despesas_s = df_mes[df_mes['Tipo'] == 'Despesa']['Valor'].sum()
            pendentes_s = df_mes[(df_mes['Tipo'] == 'Despesa') & (df_mes['Status'] == 'Pendente')]['Valor'].sum()
            
            if entradas_s > 0:
                score += 30 if despesas_s <= entradas_s else -30
                score += 20 if (entradas_s - despesas_s) >= (entradas_s * 0.20) else 0
                score -= 15 if pendentes_s > (entradas_s * 0.30) else 0
            else:
                score = 0
            score = max(0, min(100, score))
            
            col_s1, col_s2 = st.columns([1, 1])
            with col_s1:
                fig_gauge = go.Figure(go.Indicator(mode="gauge+number", value=score, domain={'x': [0, 1], 'y': [0, 1]}, gauge={'axis': {'range': [None, 100]}, 'bar': {'color': "white"}, 'steps': [{'range': [0, 40], 'color': "#EF553B"}, {'range': [40, 70], 'color': "#FFA15A"}, {'range': [70, 100], 'color': "#00CC96"}]}))
                fig_gauge.update_layout(template="plotly_dark", height=300)
                st.plotly_chart(fig_gauge, use_container_width=True)
            with col_s2:
                if entradas_s == 0: st.warning("Adicione Entradas para a análise.")
                else:
                    if score >= 70: st.success("✅ Excelente saúde financeira!")
                    elif score >= 40: st.warning("⚠️ Atenção! Está no limite.")
                    else: st.error("🚨 Crítico! Precisa de atenção.")
